import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "browser" / "runtime" / "pyb.py"
SPEC = importlib.util.spec_from_file_location("browser_pyb", MODULE_PATH)
PYB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PYB)


class UsbVcpTest(unittest.TestCase):
    def test_receive_queue_and_transmit_queue(self):
        previous_input = PYB.USB_VCP.input_path
        previous_output = PYB.USB_VCP.output_path
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "usb-in.bin"
            output_path = root / "usb-out.bin"
            PYB.USB_VCP.input_path = str(input_path)
            PYB.USB_VCP.output_path = str(output_path)
            try:
                usb = PYB.USB_VCP()
                self.assertEqual(usb.any(), 0)
                self.assertIsNone(usb.read())

                input_path.write_bytes(b"abcde")
                self.assertEqual(usb.any(), 5)
                self.assertEqual(usb.read(2), b"ab")
                self.assertEqual(usb.any(), 3)
                self.assertEqual(usb.read(), b"cde")
                self.assertFalse(input_path.exists())

                self.assertEqual(usb.write(b"response"), 8)
                self.assertEqual(usb.write("\r\n"), 2)
                self.assertEqual(output_path.read_bytes(), b"response\r\n")
                unknown_command = bytes([0x00, 0xFF, 0x81, 0x42])
                input_path.write_bytes(unknown_command)
                self.assertEqual(usb.read(), unknown_command)
                self.assertEqual(usb.write(unknown_command), len(unknown_command))
                self.assertTrue(output_path.read_bytes().endswith(unknown_command))
            finally:
                PYB.USB_VCP.input_path = previous_input
                PYB.USB_VCP.output_path = previous_output


if __name__ == "__main__":
    unittest.main()
