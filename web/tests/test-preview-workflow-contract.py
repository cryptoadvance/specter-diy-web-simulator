#!/usr/bin/env python3
"""Static check for the service workflow's trust and ownership boundaries."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/preview.yml").read_text(encoding="utf-8")


def job(name, next_name=None):
    start = WORKFLOW.index(f"  {name}:\n")
    if next_name:
        end = WORKFLOW.index(f"  {next_name}:\n", start + 1)
        return WORKFLOW[start:end]
    return WORKFLOW[start:]


class PreviewWorkflowContractTests(unittest.TestCase):
    def test_remote_service_dispatches_then_validates_live_pr(self):
        self.assertIn("workflow_dispatch:", WORKFLOW)
        self.assertNotIn("repository_dispatch:", WORKFLOW)
        self.assertIn("python3 web/tools/validate_preview_request.py", WORKFLOW)
        self.assertIn("DEFAULT_BRANCH:", WORKFLOW)
        for field in ("request_id", "base_repository", "base_sha", "base_ref",
                      "pr_number", "head_repository",
                      "head_sha", "head_ref", "source_updated_at"):
            self.assertIn(f"      {field}:", WORKFLOW)

    def test_untrusted_build_has_read_only_permissions_and_no_trusted_tests(self):
        build = job("build", "trusted_runtime")
        self.assertIn("permissions:\n      contents: read", build)
        self.assertNotIn("contents: write", build)
        self.assertNotIn("actions: write", build)
        self.assertNotIn("pages: write", build)
        self.assertNotIn("id-token: write", build)
        self.assertNotIn("secrets.", build)
        self.assertIn("persist-credentials: false", build)
        self.assertIn("ref: ${{ needs.validate.outputs.head_sha }}", build)
        self.assertIn("nix develop -c make disco", build)
        self.assertIn("build-browser.sh", build)
        self.assertIn("test-browser-manifest.py", build)
        self.assertLess(
            build.index("write-browser-manifest.py"),
            build.index("test-browser-manifest.py"),
        )
        self.assertLess(
            build.index("test-browser-manifest.py"),
            build.index("Install firmware build dependencies"),
        )
        browser_builder = (ROOT / "web/browser/build-browser.sh").read_text()
        self.assertLess(
            browser_builder.index("write-browser-manifest.py"),
            browser_builder.index("test-browser-manifest.py"),
        )
        for trusted_test in ("test:browser", "test:provenance", "test:compat",
                             "test-network-policy.mjs", "test-usb-transport.mjs",
                             "go test ./..."):
            self.assertNotIn(trusted_test, build)

    def test_only_always_finalizer_publishes_and_reports_through_narrow_app_token(self):
        finalize = job("finalize")
        self.assertIn("always()", finalize)
        self.assertIn("contents: write", finalize)
        self.assertIn("pages: write", finalize)
        self.assertIn("id-token: write", finalize)
        self.assertIn("python3 simulator/web/tools/publish_preview.py", finalize)
        self.assertIn("actions/deploy-pages@", finalize)
        self.assertIn("actions: write", finalize)
        self.assertIn("preview-publish-${{ github.repository }}", finalize)
        self.assertIn("actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1", finalize)
        self.assertIn("permission-pull-requests: write", finalize)
        self.assertIn("repositories: specter-diy", finalize)
        self.assertIn("owner: cryptoadvance", finalize)
        self.assertIn("needs.validate.outputs.base_repository == 'cryptoadvance/specter-diy'", finalize)
        self.assertIn("SPECTER_PREVIEW_APP_PRIVATE_KEY", finalize)
        self.assertIn("python3 simulator/web/tools/report_preview.py", finalize)
        self.assertNotIn("issues: write", WORKFLOW)
        self.assertNotRegex(WORKFLOW, re.compile(r"^      pull-requests: write$", re.MULTILINE))
        self.assertNotIn("SPECTER_PREVIEW_APP_PRIVATE_KEY", job("build", "trusted_runtime"))
        self.assertNotIn("SPECTER_PREVIEW_APP_PRIVATE_KEY", job("trusted_runtime", "verify"))
        self.assertNotIn("SPECTER_PREVIEW_APP_PRIVATE_KEY", job("verify", "finalize"))
        self.assertIn("actions: read", job("verify", "finalize"))
        self.assertNotIn("repository: ${{ needs.validate.outputs.head_repository }}", finalize)
        self.assertNotIn("nix develop", finalize)
        self.assertNotIn("npm ", finalize)
        self.assertNotIn("node ", finalize)
        self.assertIn("python3 simulator/web/tools/prune_firmware_artifacts.py", finalize)
        self.assertLess(finalize.index("report_preview.py"),
                        finalize.index("prune_firmware_artifacts.py"))
        publisher_source = (ROOT / "web/tools/publish_preview.py").read_text()
        self.assertNotIn("subprocess", publisher_source)
        self.assertNotIn("os.system", publisher_source)
        reporter = (ROOT / "web/tools/report_preview.py").read_text()
        self.assertIn('MARKER = "<!-- specter-web-simulator-preview -->"', reporter)
        self.assertIn("managed_comments(comments, expected_login)", reporter)
        self.assertIn('request_fn("DELETE",', reporter)
        self.assertIn('request_fn("POST",', reporter)

    def test_trusted_javascript_is_built_from_base_on_a_separate_runner(self):
        runtime = job("trusted_runtime", "verify")
        self.assertIn("runs-on: ubuntu-latest", runtime)
        self.assertIn("contents: read", runtime)
        self.assertNotIn("contents: write", runtime)
        self.assertNotIn("secrets.", runtime)
        self.assertIn("ref: ${{ needs.validate.outputs.base_sha }}", runtime)
        self.assertIn("SIMULATOR_COMMIT: ${{ github.sha }}", runtime)
        self.assertIn("SPECTER_GIT_COMMIT: ${{ needs.validate.outputs.head_sha }}", runtime)
        self.assertIn("python3 tools/embed_git_info.py", runtime)
        self.assertLess(
            runtime.index("python3 tools/embed_git_info.py"),
            runtime.index("Build trusted JavaScript from the exact validated base SHA"),
        )
        self.assertIn("package_trusted_runtime.py", runtime)
        self.assertNotIn("pip install", runtime)
        self.assertNotIn("requirements.txt", runtime)
        self.assertIn("name: trusted-micropython-runtime", runtime)

        build = job("build", "trusted_runtime")
        self.assertIn("package_browser.py", build)
        self.assertIn('ARTIFACTS = ("micropython.wasm", "micropython.data")',
                      (ROOT / "web/tools/package_browser.py").read_text())
        finalize = job("finalize")
        self.assertIn("needs: [validate, build, trusted_runtime, verify]", finalize)
        self.assertIn("name: trusted-micropython-runtime", finalize)
        self.assertIn("replace_glue(extracted", (ROOT / "web/tools/publish_preview.py").read_text())

        verify = job("verify", "finalize")
        self.assertIn("needs: [validate, build, trusted_runtime]", verify)
        self.assertIn("runs-on: ubuntu-latest", verify)
        self.assertIn("actions: read", verify)
        self.assertIn("contents: read", verify)
        self.assertIn("pull-requests: read", verify)
        self.assertIn("ACTION: ${{ needs.validate.outputs.action }}", verify)
        self.assertNotIn("contents: write", verify)
        self.assertNotIn("pages: write", verify)
        self.assertNotIn("secrets.", verify)
        self.assertNotIn("repository: ${{ needs.validate.outputs.head_repository }}", verify)
        self.assertNotIn("requirements.txt", verify)
        self.assertNotIn("nix develop", verify)
        self.assertIn("python3 simulator/web/tools/publish_preview.py", verify)
        self.assertIn("*test-browser-manifest.py", verify)
        self.assertIn("test:browser", verify)
        self.assertIn("test-network-policy.mjs", verify)
        self.assertIn("test-usb-transport.mjs", verify)
        self.assertIn("go test ./...", verify)
        self.assertIn("needs.verify.result == 'success'", finalize)

    def test_live_pr_metadata_fetch_is_authenticated_in_trusted_jobs(self):
        validate = job("validate", "build")
        finalize = job("finalize")
        verify = job("verify", "finalize")
        self.assertIn("pull-requests: read", validate)
        self.assertIn("GH_TOKEN: ${{ github.token }}", validate)
        self.assertIn("pull-requests: read", verify)
        self.assertIn("GH_TOKEN: ${{ github.token }}", verify)
        self.assertIn("pull-requests: read", finalize)
        self.assertIn("GH_TOKEN: ${{ github.token }}", finalize)
        request_tool = (ROOT / "web/tools/validate_preview_request.py").read_text()
        self.assertIn('headers["Authorization"] = f"Bearer {token}"', request_tool)

    def test_timeout_and_superseded_build_contract(self):
        build = job("build", "trusted_runtime")
        finalize = job("finalize")
        self.assertIn("timeout-minutes: 180", build)
        self.assertIn("cancel-in-progress: true", build)
        self.assertIn("timeout-minutes: 10", finalize)
        self.assertLess(180, 210)

    def test_emsdk_is_pinned_and_summary_uses_printf(self):
        build = job("build", "trusted_runtime")
        pin = (ROOT / ".preview-config/emsdk-commit").read_text().strip()
        self.assertRegex(pin, r"^[a-f0-9]{40}$")
        self.assertIn("fetch --depth 1 origin refs/tags/3.1.74", build)
        self.assertIn('rev-parse HEAD)" = "$(cat simulator/.preview-config/emsdk-commit)', build)
        self.assertIn("emsdk install 3.1.74", build)
        finalize = job("finalize")
        self.assertIn("printf 'Request:", finalize)
        self.assertNotRegex(finalize, r'echo\s+"[^\n]*`')

    def test_pr_preview_csp_removes_local_virtual_host_from_connect_sources(self):
        import sys
        tools_path = str(ROOT / "web/tools")
        if tools_path not in sys.path:
            sys.path.insert(0, tools_path)
        from preview_csp import restrict_preview_csp
        stable = (ROOT / "web/index.html").read_text(encoding="utf-8")
        preview = restrict_preview_csp(stable)
        stable_policy = re.search(
            r'http-equiv="Content-Security-Policy" content="([^"]+)', stable
        ).group(1)
        preview_policy = re.search(
            r'http-equiv="Content-Security-Policy" content="([^"]+)', preview
        ).group(1)
        self.assertIn("ws://127.0.0.1:8788", stable_policy)
        self.assertIn("connect-src 'self'", preview_policy)
        self.assertNotIn("127.0.0.1:8788", preview_policy)
        self.assertNotIn("localhost:8788", preview_policy)

    def test_actions_are_immutable_and_virtual_host_pin_is_consistent(self):
        uses = re.findall(r"uses:\s+[^\s@]+@([^\s#]+)", WORKFLOW)
        self.assertTrue(uses)
        self.assertTrue(all(re.fullmatch(r"[a-f0-9]{40}", value) for value in uses), uses)
        pin = (ROOT / ".preview-config/virtual-host-commit").read_text().strip()
        self.assertEqual(pin, "3cf3ecd58a97da0f2cc4b7586ca33abf02f68372")
        self.assertIn(f"ref: {pin}", WORKFLOW)

    def test_preview_urls_are_per_commit_and_only_latest_page_is_retained(self):
        publisher = (ROOT / "web/tools/publish_preview.py").read_text()
        self.assertIn('pages / "pr" / str(request["pr_number"]) / request["head_sha"]', publisher)
        self.assertIn("_remove_superseded_previews(pages, request[\"pr_number\"], request[\"head_sha\"])", publisher)
        self.assertIn('"successful_previews": [] if effective == "deleted" else successful', publisher)
        self.assertIn('"latest_run_url": run_url', publisher)
        pruner = (ROOT / "web/tools/prune_pages.py").read_text()
        self.assertIn("PAGES_BUDGET_BYTES = 950_000_000", pruner)
        self.assertIn("_remove_tree(pages, pages / \"pr\" / str(pr_number))", pruner)
        self.assertIn("prune_pages.py", WORKFLOW)
        self.assertIn("report-capacity-evictions", WORKFLOW)
        self.assertIn("PAGES_DIR", WORKFLOW)
        self.assertIn('os.environ["PR_NUMBER"] / os.environ["EXPECTED_SHA"]', WORKFLOW)
        self.assertIn('"$PAGES_DIR/pr/$PR_NUMBER/$HEAD_SHA"', WORKFLOW)
        self.assertIn("workflow_run_id", publisher)
        staging = (ROOT / "web/tools/stage_pages_site.py").read_text()
        self.assertIn('("pr", "status")', staging)
        self.assertNotIn(".preview-state", staging)

    def test_only_latest_firmware_artifact_is_retained_per_pr(self):
        build = job("build", "trusted_runtime")
        finalize = job("finalize")
        self.assertIn("retention-days: 90", build)
        self.assertIn(
            "name: specter-firmware-pr-${{ needs.validate.outputs.pr_number }}-run-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            build,
        )
        self.assertNotIn("overwrite: true", build)
        self.assertIn("FIRMWARE_ARTIFACTS_TO_PRUNE", finalize)
        self.assertIn('"successful_previews": [] if effective == "deleted" else successful',
                      (ROOT / "web/tools/publish_preview.py").read_text())


if __name__ == "__main__":
    unittest.main()
