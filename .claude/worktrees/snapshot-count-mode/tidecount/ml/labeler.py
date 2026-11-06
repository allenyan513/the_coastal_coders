"""A notebook widget for marking fish on still frames, with one click per fish."""
import base64
import io
import json
from pathlib import Path

import anywidget
import traitlets
from PIL import Image


class FishLabeler(anywidget.AnyWidget):
    """Shows frames one at a time and saves each answer to a JSON file straight away."""

    _esm = """
    function render({ model, el }) {
      const root = document.createElement("div");
      root.className = "fish-labeler";
      root.tabIndex = 0;
      root.innerHTML = `
        <p class="status"></p>
        <canvas></canvas>
        <div class="buttons">
          <button data-do="back">Back (B)</button>
          <button data-do="undo">Undo (Z)</button>
          <button data-do="unclear">Can't tell (U)</button>
          <button data-do="next" class="primary">Save and next (N)</button>
          <label><input type="checkbox"> Brighten</label>
        </div>`;
      el.appendChild(root);

      const canvas = root.querySelector("canvas");
      const context = canvas.getContext("2d");
      const status = root.querySelector(".status");
      const picture = new Image();
      let dots = [];

      function draw() {
        context.drawImage(picture, 0, 0, canvas.width, canvas.height);
        for (const [x, y] of dots) {
          context.beginPath();
          context.arc(x * canvas.width, y * canvas.height, 6, 0, 2 * Math.PI);
          context.lineWidth = 3;
          context.strokeStyle = "#000";
          context.stroke();
          context.lineWidth = 1.5;
          context.strokeStyle = "#ff0";
          context.stroke();
        }
        const saved = model.get("saved");
        status.textContent = saved
          ? `Frame ${model.get("index") + 1} of ${model.get("total")} · ${dots.length} fish marked · ${model.get("done")} answered · saved as ${saved}`
          : `Frame ${model.get("index") + 1} of ${model.get("total")} · ${dots.length} fish marked · ${model.get("done")} answered`;
      }
      function load() {
        dots = model.get("points").map((p) => [...p]);
        picture.src = model.get("src");
      }
      picture.onload = () => {
        canvas.width = picture.naturalWidth;
        canvas.height = picture.naturalHeight;
        draw();
        root.focus({ preventScroll: true });
      };
      function act(what) {
        if (what === "undo") { dots.pop(); draw(); return; }
        model.send({ action: what, points: dots });
      }

      canvas.addEventListener("click", (event) => {
        const box = canvas.getBoundingClientRect();
        const x = (event.clientX - box.left) / box.width;
        const y = (event.clientY - box.top) / box.height;
        const near = dots.findIndex(([a, b]) => Math.hypot((a - x) * box.width, (b - y) * box.height) < 12);
        if (near >= 0) dots.splice(near, 1);
        else dots.push([x, y]);
        draw();
      });
      root.querySelectorAll("button").forEach((button) =>
        button.addEventListener("click", () => act(button.dataset.do)));
      root.querySelector("input").addEventListener("change", (event) => {
        canvas.style.filter = event.target.checked ? "brightness(1.8) contrast(1.15)" : "none";
      });
      root.addEventListener("keydown", (event) => {
        const what = { n: "next", u: "unclear", b: "back", z: "undo" }[event.key.toLowerCase()];
        if (!what) return;
        event.preventDefault();
        event.stopPropagation();
        act(what);
      });
      model.on("change:src", load);
      load();
    }
    export default { render };
    """
    _css = """
    .fish-labeler { outline: none; }
    .fish-labeler canvas { display: block; max-width: 100%; height: auto; cursor: crosshair; }
    .fish-labeler .status { margin: 0 0 6px; font-size: 13px; }
    .fish-labeler .buttons { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; }
    .fish-labeler button { padding: 6px 12px; cursor: pointer; }
    .fish-labeler .primary { font-weight: 600; }
    """

    index = traitlets.Int(0).tag(sync=True)
    total = traitlets.Int(0).tag(sync=True)
    done = traitlets.Int(0).tag(sync=True)
    src = traitlets.Unicode("").tag(sync=True)
    points = traitlets.List([]).tag(sync=True)
    saved = traitlets.Unicode("").tag(sync=True)

    def __init__(self, frames: list[Path], labels_path: Path):
        super().__init__(total=len(frames))
        self.frames = frames
        self.labels_path = labels_path
        self.labels = json.loads(labels_path.read_text()) if labels_path.exists() else {}
        self.on_msg(self._on_message)
        first_open = next((i for i, f in enumerate(frames) if f.name not in self.labels), 0)
        self._show(first_open)

    def _on_message(self, _widget, content, _buffers) -> None:
        action = content["action"]
        if action == "back":
            self._show(max(0, self.index - 1))
            return
        status = "unclear" if action == "unclear" else "labelled"
        points = [] if status == "unclear" else content["points"]
        self.labels[self.frames[self.index].name] = {"status": status, "points": points}
        self.labels_path.write_text(json.dumps(self.labels, indent=1))
        self._show(min(len(self.frames) - 1, self.index + 1))

    def _show(self, index: int) -> None:
        frame = self.frames[index]
        answer = self.labels.get(frame.name, {})
        buffer = io.BytesIO()
        Image.open(frame).convert("RGB").save(buffer, "JPEG", quality=92)
        encoded = base64.b64encode(buffer.getvalue()).decode()
        self.index = index
        self.done = len(self.labels)
        self.saved = answer.get("status", "")
        self.points = answer.get("points", [])
        self.src = f"data:image/jpeg;base64,{encoded}"
