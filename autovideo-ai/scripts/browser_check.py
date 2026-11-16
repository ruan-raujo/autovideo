"""End-to-end checks in installed Edge, using an isolated server and database."""
from contextlib import contextmanager
import json
from io import BytesIO
from PIL import Image
from pathlib import Path
import socket
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright, expect
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import Config
from backend.main import create_app
from models.entities import Job, Video, GenerationEvent

ARTIFACTS = ROOT / "tests" / "artifacts"


@contextmanager
def isolated_server():
    with tempfile.TemporaryDirectory(prefix="autovideo-browser-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        app = create_app(Config(data_dir=Path(directory), worker_enabled=True))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, name="browser-check-server", daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if not thread.is_alive():
                    raise RuntimeError("Servidor isolado não iniciou.")
                try:
                    with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("Servidor não respondeu no prazo.")
            yield url, app
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("Servidor de teste não encerrou no prazo.")


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    report = {"browser": "Microsoft Edge", "checks": [], "viewports": [], "page_errors": []}
    with isolated_server() as (url, app), sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="pt-BR", reduced_motion="reduce")
        page = context.new_page()
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        try:
            assert page.goto(url).status == 200
            expect(page.locator("#connection")).to_contain_text("conectado")
            expect(page.locator("#jobs")).to_contain_text("Sua próxima história começa aqui")
            page.keyboard.press("Tab")
            expect(page.get_by_role("link", name="Pular para o conteúdo")).to_be_focused()
            for _ in range(15):
                page.keyboard.press("Tab")
                focus = page.evaluate("""() => {
                    const el = document.activeElement;
                    if (el === document.body) return null;
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return {tag: el.tagName, visible: rect.bottom > 0 && rect.top < innerHeight,
                            outlined: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 2};
                }""")
                assert focus is None or (focus["visible"] and focus["outlined"]), focus
            page.evaluate("window.scrollTo(0, 0)")
            report["checks"].append("initial page, database connection, keyboard skip link and visible tab focus")

            page.locator("#topic").fill("E se o Sol desaparecesse?")
            page.locator("#submit-button").click()
            expect(page.locator("#create-status")).to_contain_text("Projeto adicionado")
            expect(page.locator("#jobs")).to_contain_text("Aguardando roteiro ou geração", timeout=15000)
            assert page.request.get(url + "/api/videos").json()["total"] == 1
            # A focused action must not freeze progress/message polling.
            focus_button = page.get_by_role("button", name="Ver detalhes", exact=True)
            focus_button.focus()
            with app.state.queue.sessions.begin() as session:
                row = session.get(Job, page.request.get(url + "/api/videos").json()["items"][0]["id"])
                row.message = "Atualização da fila com foco de teclado preservado."
            expect(page.locator("#jobs")).to_contain_text("Atualização da fila com foco", timeout=10000)
            expect(page.get_by_role("button", name="Ver detalhes", exact=True)).to_be_focused()
            report["checks"].append("real creation and background project preparation")

            page.get_by_role("button", name="Ver detalhes", exact=True).click()
            expect(page.locator("#job-dialog")).to_be_visible()
            expect(page.locator("#event-list")).to_contain_text("Projeto preparado")
            expect(page.locator("#detail-info")).to_contain_text("JSON do projeto salvo")
            page.keyboard.press("Escape")
            expect(page.locator("#job-dialog")).not_to_be_visible()
            report["checks"].append("details dialog, persisted event history and escape key")

            page.get_by_role("button", name="Editar roteiro", exact=True).click()
            expect(page.locator("#script-dialog")).to_be_visible()
            example = page.request.get(url + "/api/examples/sun").json()["script"]
            page.locator("#script-dialog details summary").click()
            page.locator("#script-json").fill(json.dumps(example, ensure_ascii=False))
            page.locator("#apply-json").click()
            expect(page.locator("#scene-editor fieldset")).to_have_count(10)
            expect(page.locator("#script-totals")).to_contain_text("2400 / 2400")
            page.get_by_role("button", name="Salvar roteiro", exact=True).click()
            expect(page.locator("#script-status")).to_contain_text("Roteiro salvo")
            page.locator("#close-editor").click()
            expect(page.get_by_role("button", name="Gerar vídeo PT", exact=True)).to_be_visible()
            page.get_by_role("button", name="Gerar vídeo PT", exact=True).click()
            expect(page.locator("#queue-error")).to_contain_text("instalar_midia.bat")
            report["checks"].append("scene editor, 80-second script persistence and missing media dependency error")

            page.locator("#topic").fill("E SE O SOL DESAPARECESSE!!!")
            page.locator("#submit-button").click()
            expect(page.locator("#topic-error")).to_contain_text("já existe")
            expect(page.locator("#topic")).to_have_value("E SE O SOL DESAPARECESSE!!!")
            report["checks"].append("duplicate rejection preserves input")

            long_topic = "E se " + "a" * 285 + " <script>?"
            page.locator("#topic").fill(long_topic)
            page.locator("#submit-button").click()
            expect(page.locator("#total-count")).to_have_text("2")
            expect(page.locator("#jobs .job-row")).to_have_count(2)
            expect(page.locator("#jobs .status-badge.awaiting_renderer")).to_have_count(2, timeout=15000)
            assert page.locator("#jobs script").count() == 0
            report["checks"].append("long unbreakable text and HTML rendered safely as text")

            first_row = page.locator(".job-row").filter(has=page.get_by_role("heading", name="E se o Sol desaparecesse?", exact=True))
            first_row.get_by_role("button", name="Cancelar trabalho").click()
            expect(first_row).to_contain_text("Cancelado")
            page.locator("#status-filter").select_option("cancelled")
            expect(page.locator(".job-row")).to_have_count(1)
            expect(page.locator("#jobs")).to_contain_text("E se o Sol desaparecesse?")
            page.locator("#status-filter").select_option("")
            expect(page.locator(".job-row")).to_have_count(2)
            report["checks"].append("cancellation and status filter")

            page.locator("#poll-seconds").fill("0.5")
            page.locator("#music-enabled").check()
            page.locator("#sfx-enabled").check()
            page.locator("#encoder").select_option("cpu")
            page.get_by_role("button", name="Salvar configurações").click()
            expect(page.locator("#settings-status")).to_contain_text("Configurações salvas")
            page.reload()
            expect(page.locator("#poll-seconds")).to_have_value("0.5")
            expect(page.locator("#music-enabled")).to_be_checked()
            expect(page.locator("#sfx-enabled")).to_be_checked()
            expect(page.locator("#encoder")).to_have_value("cpu")
            expect(page.locator("#total-count")).to_have_text("2")
            report["checks"].append("settings and projects survive browser reload")

            # Remove the error fixture from screenshots by selecting the short topic's state.
            page.locator("#status-filter").select_option("cancelled")
            expect(page.locator(".job-row")).to_have_count(1)
            for width, height in ((1440, 900), (1024, 768), (820, 1180), (768, 1024), (390, 844), (320, 800)):
                page.set_viewport_size({"width": width, "height": height})
                page.evaluate("window.scrollTo(0, 0)")
                # Test worst case text as well as the screenshot's short project.
                page.locator("#status-filter").select_option("")
                expect(page.locator(".job-row")).to_have_count(2)
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                assert not overflow, f"Horizontal overflow at {width}px"
                overlaps = page.locator(".environment > div, .pipeline li").evaluate_all("""rows => rows.filter(row => {
                    const children = [...row.children].filter(el => getComputedStyle(el).display !== 'none');
                    return children.some((child, index) => index && child.getBoundingClientRect().left < children[index-1].getBoundingClientRect().right - 1);
                }).map(row => row.textContent)""")
                assert not overlaps, f"Text overlaps at {width}px: {overlaps}"
                page.locator("#status-filter").select_option("cancelled")
                expect(page.locator(".job-row")).to_have_count(1)
                page.screenshot(path=str(ARTIFACTS / f"studio-{width}.png"), full_page=True)
                report["viewports"].append({"width": width, "height": height, "overflow": False, "overlap": False})
            report["checks"].append("responsive layout and worst case topic at six viewport widths")

            builtin_count=len(page.request.get(url+"/api/assets").json()["items"])
            expect(page.locator(".asset-card")).to_have_count(builtin_count)
            stream=BytesIO(); Image.new("RGB",(32,32),"green").save(stream,"PNG")
            page.get_by_role("textbox",name="Nome do recurso",exact=True).fill("Imagem de QA")
            page.get_by_role("textbox",name="Licença do recurso",exact=True).fill("Próprio")
            page.get_by_label("Arquivo de imagem",exact=True).set_input_files({"name":"qa.png","mimeType":"image/png","buffer":stream.getvalue()})
            page.get_by_role("button",name="Importar imagem",exact=True).click()
            expect(page.locator(".asset-card")).to_have_count(builtin_count+1)
            page.locator(".asset-card").filter(has_text="Imagem de QA").get_by_role("button",name="Excluir",exact=True).click()
            expect(page.locator(".asset-card")).to_have_count(builtin_count)
            page.locator("#quantity").fill("2")
            page.locator("#quantity").dispatch_event("change")
            expect(page.locator("#automatic")).to_be_checked()
            expect(page.locator("#automatic")).to_be_disabled()
            page.locator("#quantity").fill("1")
            page.locator("#quantity").dispatch_event("change")
            page.locator("#automatic").uncheck()
            report["checks"].append("visual library upload/delete, batch quantity mode and persistent audio/encoder settings")

            for language in ("PT","EN"):
                demo = ROOT / "output/acceptance" / f"video_001_{language}.mp4"
                assert demo.is_file(),f"Missing actual {language} acceptance video"
                # Import the REAL, previously rendered clip into this isolated QA database.
                # No fake media is used, and the user's projects are not touched.
                imported = page.request.post(url + "/api/videos", data={"topic": f"Verificação de reprodução do vídeo validado {language}"}).json()
                for _ in range(100):
                    current = page.request.get(url + f"/api/videos/{imported['id']}").json()
                    if current["preparation_complete"]:
                        break
                    time.sleep(.05)
                folder = app.state.queue.data_dir / "output" / imported["story_id"]
                media = folder / f"playback_{language}.mp4"
                shutil.copyfile(demo, media)
                metadata = json.loads((ROOT / "output/acceptance" / f"video_001_{language}.validation.json").read_text(encoding="utf-8"))
                with app.state.queue.sessions.begin() as session:
                    job = session.get(Job, imported["id"])
                    job.status, job.task, job.progress = "completed", "render", 100
                    session.add(Video(story_id=job.story_id, language=language, file_path=str(media.relative_to(app.state.queue.data_dir)), metadata_json=metadata))
                    session.add(GenerationEvent(job_id=job.id, status="completed", message="Vídeo real importado exclusivamente para verificar o player no navegador."))
                page.locator("#status-filter").select_option("completed")
                expect(page.locator(".job-row")).to_have_count(1 if language=="PT" else 2)
                page.locator(".job-row").filter(has_text=f"vídeo validado {language}").get_by_role("button", name="Ver detalhes", exact=True).click()
                player = page.locator("#media-preview video")
                expect(player).to_be_visible()
                for _ in range(200):
                    if player.evaluate("video => video.readyState >= 1"):
                        break
                    time.sleep(.05)
                dimensions = player.evaluate("video => ({duration: video.duration, width: video.videoWidth, height: video.videoHeight})")
                assert dimensions == {"duration": 80, "width": 1080, "height": 1920}, dimensions
                player.evaluate("video => { video.muted = true; return video.play(); }")
                for _ in range(200):
                    if player.evaluate("video => video.currentTime > 0.2"):
                        break
                    time.sleep(.05)
                assert player.evaluate("video => video.currentTime > 0.2")
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(ARTIFACTS / f"player-{language}-390.png"), full_page=True)
                page.locator("#close-dialog").click()
                report["checks"].append(f"REAL {language} MP4 playback in Edge: 80s, 1080x1920, HTTP range requests and working video player")

            page.route("**/api/videos?**", lambda route: route.abort())
            page.locator("#refresh").click()
            expect(page.locator("#queue-error")).to_contain_text("Não foi possível acessar")
            expect(page.locator("#connection")).to_contain_text("Sem conexão")
            report["checks"].append("network failure is visible without discarding listed projects")
            assert not report["page_errors"], report["page_errors"]
            report["result"] = "passed"
        except Exception:
            page.screenshot(path=str(ARTIFACTS / "failure.png"), full_page=True)
            report["result"] = "failed"
            raise
        finally:
            (ARTIFACTS / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
