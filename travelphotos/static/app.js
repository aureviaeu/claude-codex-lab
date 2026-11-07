"use strict";
(function () {
  const token = document.querySelector('meta[name="token"]').content;
  const $ = (id) => document.getElementById(id);
  let state = null;
  let chatText = "";

  async function api(path, body) {
    const opts = { headers: { "X-Token": token } };
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({ error: "伺服器回應無法讀取" }));
    if (!res.ok) throw new Error(data.error || "發生錯誤");
    return data;
  }

  function setStatus(el, text, isError) {
    el.textContent = text;
    el.classList.toggle("error", !!isError);
  }

  function readFile(input) {
    return new Promise((resolve, reject) => {
      const file = input.files && input.files[0];
      if (!file) return resolve("");
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("無法讀取檔案"));
      reader.readAsText(file, "utf-8");
    });
  }

  $("itinerary-file").addEventListener("change", async (e) => {
    $("itinerary").value = await readFile(e.target);
  });
  $("chat-file").addEventListener("change", async (e) => {
    chatText = await readFile(e.target);
  });

  $("scan").addEventListener("click", async () => {
    const btn = $("scan");
    btn.disabled = true;
    setStatus($("scan-status"), "掃描中，照片多時需要一點時間…");
    try {
      state = await api("/api/scan", {
        input_dir: $("input-dir").value,
        itinerary: $("itinerary").value,
        line_chat: chatText,
      });
      setStatus($("scan-status"), "完成。");
      render();
    } catch (err) {
      setStatus($("scan-status"), err.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  async function arrange(manualOrder, assignments) {
    try {
      state = await api("/api/arrange", {
        assignments: assignments === undefined ? state.assignments : assignments,
        manual_order: manualOrder,
      });
      render();
    } catch (err) {
      setStatus($("apply-status"), err.message, true);
    }
  }

  $("reset-order").addEventListener("click", () => arrange(null));

  $("apply").addEventListener("click", async () => {
    const btn = $("apply");
    btn.disabled = true;
    setStatus($("apply-status"), "複製中…");
    try {
      const data = await api("/api/apply", { output_dir: $("output-dir").value });
      const a = data.applied;
      let msg = `完成：輸出 ${a.written} 個檔案（新複製 ${a.copied}，重新命名 ${a.renamed}），略過重複 ${a.duplicates_skipped} 個。`;
      if (a.face_excluded) msg += `人物篩選排除 ${a.face_excluded} 個（列在報告中）。`;
      msg += `報告：${a.report}`;
      if (a.leftovers.length) msg += `。上次輸出但這次不在清單中的檔案已改名為「未使用_…」：${a.leftovers.length} 個`;
      setStatus($("apply-status"), msg);
      state = data;
      render();
    } catch (err) {
      setStatus($("apply-status"), err.message, true);
    } finally {
      btn.disabled = false;
    }
  });

  function li(text) {
    const el = document.createElement("li");
    el.textContent = text;
    return el;
  }

  function render() {
    if (!state || !state.scanned) return;
    $("step-review").hidden = false;
    $("step-output").hidden = false;
    const dups = state.duplicates.length;
    let summary = `輸入 ${state.input_media} 個照片／影片，重複 ${dups} 個，將輸出 ${state.files.length} 個。`;
    if (!state.similarity) summary += " （未安裝 Pillow，無法用內容相似度分組。）";
    $("summary").textContent = summary;

    $("dup-box").hidden = dups === 0;
    $("dups").replaceChildren(...state.duplicates.map((d) => li(`${d.id}（與 ${d.duplicate_of} 相同）`)));
    $("skip-box").hidden = state.skipped.length === 0;
    $("skipped").replaceChildren(...state.skipped.map((s) => li(s)));

    $("chat-box").hidden = state.chat.length === 0;
    const head = document.createElement("tr");
    ["日期", "照片／影片訊息", "第一則", "最後一則"].forEach((t) => {
      const th = document.createElement("th");
      th.textContent = t;
      head.appendChild(th);
    });
    const rows = state.chat.map((c) => {
      const tr = document.createElement("tr");
      [c.date, String(c.count), c.first, c.last].forEach((t) => {
        const td = document.createElement("td");
        td.textContent = t;
        tr.appendChild(td);
      });
      return tr;
    });
    $("chat").replaceChildren(head, ...rows);

    renderGroups();
    renderGrid();
    renderFaces();
  }

  function renderGroups() {
    const box = $("groups-box");
    box.hidden = state.stops.length === 0;
    if (box.hidden) return;
    const byGroup = {};
    state.files.forEach((f) => (byGroup[f.group] = byGroup[f.group] || []).push(f.id));
    const rows = state.groups.map((g) => {
      const row = document.createElement("div");
      row.className = "group-row";
      const label = document.createElement("span");
      label.textContent = `第 ${g.id} 組（${g.size} 個，從 ${g.first} 開始）`;
      const select = document.createElement("select");
      select.setAttribute("aria-label", `第 ${g.id} 組的行程站點`);
      const none = document.createElement("option");
      none.value = "";
      none.textContent = "未對應";
      select.appendChild(none);
      state.stops.forEach((s) => {
        const opt = document.createElement("option");
        opt.value = String(s.index);
        opt.textContent = `${s.index}. 第${s.day}天 ${s.name}`;
        select.appendChild(opt);
      });
      select.value = g.stop ? String(g.stop) : "";
      select.addEventListener("change", () => {
        const next = Object.assign({}, state.assignments);
        (byGroup[g.id] || []).forEach((id) => delete next[id]);
        if (select.value) next[g.first] = Number(select.value);
        if (state.manual && !confirm("變更站點會還原自動順序，手動調整會消失。要繼續嗎？")) {
          select.value = g.stop ? String(g.stop) : "";
          return;
        }
        arrange(null, next);
      });
      row.append(label, select);
      return row;
    });
    $("groups").replaceChildren(...rows);
  }

  let dragId = null;

  function currentIds() {
    return state.files.map((f) => f.id);
  }

  function moveTo(id, targetIndex) {
    const ids = currentIds();
    const from = ids.indexOf(id);
    if (from < 0 || targetIndex < 0 || targetIndex >= ids.length || from === targetIndex) return;
    ids.splice(from, 1);
    ids.splice(targetIndex, 0, id);
    arrange(ids);
  }

  function renderGrid() {
    const items = state.files.map((f, i) => {
      const el = document.createElement("li");
      const faceOut = state.faces.enabled && f.face && !f.face.keep;
      el.className = "item" + (f.manual ? " manual" : "") + (faceOut ? " face-out" : "");
      el.draggable = true;
      el.dataset.id = f.id;

      let thumb;
      if (f.kind === "photo") {
        thumb = document.createElement("img");
        thumb.loading = "lazy";
        thumb.alt = f.name;
        thumb.src = `/api/thumb?id=${encodeURIComponent(f.id)}&token=${encodeURIComponent(token)}`;
        thumb.addEventListener("error", () => {
          const ph = document.createElement("div");
          ph.className = "thumb";
          ph.textContent = "無法預覽";
          thumb.replaceWith(ph);
        });
      } else {
        thumb = document.createElement("div");
        thumb.textContent = "影片";
      }
      thumb.classList.add("thumb");

      const top = document.createElement("div");
      const pos = document.createElement("span");
      pos.className = "pos";
      pos.textContent = `${f.position}. `;
      const badge = document.createElement("span");
      badge.className = `badge ${f.confidence}`;
      badge.textContent = `可信度 ${f.confidence_label}`;
      top.append(pos, badge);

      const name = document.createElement("div");
      name.className = "name";
      name.textContent = f.id;
      const basis = document.createElement("div");
      basis.className = "basis";
      basis.textContent = f.basis;

      const up = document.createElement("button");
      up.type = "button";
      up.className = "move";
      up.textContent = "往前";
      up.disabled = i === 0;
      up.addEventListener("click", () => moveTo(f.id, i - 1));
      const down = document.createElement("button");
      down.type = "button";
      down.className = "move";
      down.textContent = "往後";
      down.disabled = i === state.files.length - 1;
      down.addEventListener("click", () => moveTo(f.id, i + 1));

      el.append(thumb, top, name, basis);
      if (f.face) {
        const fb = document.createElement("div");
        fb.className = `face-badge ${f.face.status}`;
        fb.textContent = `${f.face.label}：${f.face.reason}`;
        el.append(fb);
      }
      el.append(up, down);

      el.addEventListener("dragstart", (e) => {
        dragId = f.id;
        el.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", f.id);
      });
      el.addEventListener("dragend", () => {
        dragId = null;
        el.classList.remove("dragging");
      });
      el.addEventListener("dragover", (e) => {
        if (dragId && dragId !== f.id) {
          e.preventDefault();
          el.classList.add("over");
        }
      });
      el.addEventListener("dragleave", () => el.classList.remove("over"));
      el.addEventListener("drop", (e) => {
        e.preventDefault();
        el.classList.remove("over");
        if (dragId && dragId !== f.id) moveTo(dragId, i);
      });
      return el;
    });
    $("grid").replaceChildren(...items);
  }

  // --- only me and family (#6, docs/decisions/0009-local-face-recognition.md) ---
  async function faceAction(action, body, busyText, doneText) {
    const status = $("faces-status");
    const buttons = Array.from($("step-faces").querySelectorAll("button, input"));
    buttons.forEach((b) => (b.disabled = true));
    if (busyText) setStatus(status, busyText);
    try {
      const data = await api(`/api/faces/${action}`, body);
      state = data;
      render();
      setStatus(status, typeof doneText === "function" ? doneText(data) : doneText || "");
    } catch (err) {
      setStatus(status, err.message, true);
    } finally {
      buttons.forEach((b) => (b.disabled = false));
      if (state && state.faces) renderFaces();
    }
  }

  function selectPeople(ids, enabled) {
    faceAction("select", { person_ids: ids, enabled: enabled });
  }

  function renderFaces() {
    const fs = state.faces;
    $("step-faces").hidden = false;
    $("faces-unavailable").hidden = fs.available && !fs.store_error;
    $("faces-unavailable").textContent = fs.message || fs.store_error || "";
    $("faces-path").textContent = fs.data_path;
    $("face-analyze").disabled = !fs.available;
    $("ref-add").disabled = !fs.available;
    $("face-interval").value = String(fs.interval);
    $("face-enabled").checked = fs.enabled;

    const people = fs.people.map((p) => {
      const item = document.createElement("li");
      const label = document.createElement("label");
      label.className = "check";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = fs.selected.includes(p.id);
      box.addEventListener("change", () => {
        const ids = fs.selected.filter((x) => x !== p.id);
        if (box.checked) ids.push(p.id);
        selectPeople(ids, fs.enabled);
      });
      const name = document.createElement("span");
      name.textContent = p.name;
      label.append(box, name);
      const count = document.createElement("span");
      count.className = "count";
      count.textContent = `（${p.count} 個人臉樣本）`;
      const rename = document.createElement("button");
      rename.type = "button";
      rename.className = "move";
      rename.textContent = "改名";
      rename.addEventListener("click", () => {
        const next = prompt("新的名字", p.name);
        if (next !== null) faceAction("rename", { person_id: p.id, name: next }, "", "已改名。");
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "secondary danger move";
      remove.textContent = "移除";
      remove.addEventListener("click", () => {
        if (confirm(`要移除「${p.name}」和這個人的人臉資料嗎？`)) faceAction("remove", { person_id: p.id }, "", "已移除。");
      });
      item.append(label, count, rename, remove);
      return item;
    });
    if (!people.length) people.push(li("還沒有保存任何人。可以先按「偵測人臉」再從分組中選，或用參考照片新增。"));
    $("people").replaceChildren(...people);

    $("clusters-box").hidden = !fs.analyzed;
    const cards = fs.clusters.map((c) => {
      const card = document.createElement("div");
      card.className = "cluster";
      const title = document.createElement("div");
      title.textContent = `第 ${c.id} 組：${c.faces} 張人臉，出現在 ${c.files} 個檔案` + (c.person ? `（看起來是「${c.person}」）` : "");
      const faces = document.createElement("div");
      faces.className = "faces";
      c.samples.forEach((i) => {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = `第 ${c.id} 組的人臉`;
        img.src = `/api/faces/crop?face=${i}&token=${encodeURIComponent(token)}`;
        faces.appendChild(img);
      });
      const row = document.createElement("div");
      row.className = "row";
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = "名字";
      input.setAttribute("aria-label", `第 ${c.id} 組的名字`);
      const save = document.createElement("button");
      save.type = "button";
      save.className = "secondary move";
      save.textContent = "存成這個人";
      save.addEventListener("click", () =>
        faceAction("save-cluster", { cluster_id: c.id, name: input.value }, "", (d) => `已保存「${d.saved}」。記得勾選要保留的人。`)
      );
      row.append(input, save);
      if (fs.people.length) {
        const pick = document.createElement("select");
        pick.setAttribute("aria-label", `第 ${c.id} 組要加到誰`);
        fs.people.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p.id;
          opt.textContent = p.name;
          pick.appendChild(opt);
        });
        const add = document.createElement("button");
        add.type = "button";
        add.className = "secondary move";
        add.textContent = "加到";
        add.addEventListener("click", () =>
          faceAction("save-cluster", { cluster_id: c.id, person_id: pick.value }, "", (d) => `已加到「${d.saved}」。`)
        );
        row.append(add, pick);
      }
      card.append(title, faces, row);
      return card;
    });
    if (fs.analyzed && !cards.length) {
      const none = document.createElement("p");
      none.textContent = "沒有偵測到任何人臉。";
      cards.push(none);
    }
    $("clusters").replaceChildren(...cards);

    let summary = "";
    if (fs.counts) {
      summary = `依目前勾選：保留 ${fs.counts.kept} 個（其中不確定 ${fs.counts.uncertain} 個），排除 ${fs.counts.excluded} 個。`;
      summary += fs.enabled ? "輸出時只會複製保留的檔案，排除的會列在報告中。" : "勾選上面的選項後，輸出才會套用。";
    } else if (fs.enabled) {
      summary = fs.analyzed ? "請勾選至少一個要保留的人。" : "請先按「偵測人臉」。";
    }
    $("face-summary").textContent = summary;
  }

  $("face-analyze").addEventListener("click", () =>
    faceAction("analyze", { interval: Number($("face-interval").value) }, "偵測人臉中，照片和影片多時需要一些時間…", (d) =>
      `完成：找到 ${d.faces.clusters.reduce((n, c) => n + c.faces, 0)} 張人臉，分成 ${d.faces.clusters.length} 組。`
    )
  );
  $("face-enabled").addEventListener("change", (e) => selectPeople(state.faces.selected, e.target.checked));
  $("pick-ref").addEventListener("click", () => openPicker($("ref-dir"), false, "選擇參考照片資料夾"));
  $("ref-add").addEventListener("click", () =>
    faceAction("reference", { name: $("ref-name").value, folder: $("ref-dir").value }, "讀取參考照片中…", (d) => {
      const r = d.reference;
      let msg = `已加入「${r.person}」：使用 ${r.used.length} 張照片。`;
      if (r.skipped.length) msg += `沒有偵測到人臉而略過：${r.skipped.join("、")}。`;
      return msg + "記得勾選要保留的人。";
    })
  );
  $("faces-delete").addEventListener("click", () => {
    if (!confirm("要刪除這台電腦上保存的所有人臉資料嗎？保存的人物都會消失，照片不受影響。")) return;
    faceAction("delete-all", {}, "", (d) => (d.deleted ? "已刪除本機人臉資料。" : "沒有保存的人臉資料；這次偵測的結果也已清除。"));
  });

  // --- folder picker (docs/decisions/0006-in-page-folder-picker.md) ---------
  const picker = { field: null, listing: null };

  function pickerButton(text, onClick) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = text;
    btn.addEventListener("click", onClick);
    return btn;
  }

  function showListing(listing) {
    picker.listing = listing;
    $("picker-path").textContent = listing.path;
    $("picker-up").disabled = !listing.parent;
    const roots = $("picker-roots");
    roots.hidden = listing.roots.length < 2;
    roots.replaceChildren(
      ...listing.roots.map((r) => {
        const opt = document.createElement("option");
        opt.value = r;
        opt.textContent = r;
        return opt;
      })
    );
    const current = listing.roots.find((r) => listing.path.toUpperCase().startsWith(r.toUpperCase()));
    if (current) roots.value = current;
    const items = listing.folders.map((f) => {
      const item = document.createElement("li");
      item.appendChild(pickerButton(`📁 ${f.name}`, () => browse(f.path)));
      return item;
    });
    if (!items.length) {
      const empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "（沒有子資料夾）";
      items.push(empty);
    }
    $("picker-list").replaceChildren(...items);
    $("picker-list").scrollTop = 0;
  }

  async function browse(path) {
    setStatus($("picker-status"), "讀取中…");
    try {
      showListing(await api(`/api/folders?path=${encodeURIComponent(path)}`));
      setStatus($("picker-status"), "");
      return true;
    } catch (err) {
      setStatus($("picker-status"), err.message, true);
      return false;
    }
  }

  async function openPicker(field, allowCreate, title) {
    picker.field = field;
    picker.listing = null;
    $("picker-title").textContent = title || (allowCreate ? "選擇輸出資料夾" : "選擇照片資料夾");
    $("picker-new").hidden = !allowCreate;
    $("picker-new-name").value = "";
    $("picker-list").replaceChildren();
    $("picker-path").textContent = "";
    $("picker").showModal();
    const start = field.value.trim();
    if (start && (await browse(start))) return;
    // An empty output field starts next to the photo folder, where a new output folder usually goes.
    const photos = $("input-dir").value.trim();
    if (allowCreate && photos && (await browse(photos))) {
      if (picker.listing.parent) await browse(picker.listing.parent);
      return;
    }
    await browse("");
  }

  $("pick-input").addEventListener("click", () => openPicker($("input-dir"), false));
  $("pick-output").addEventListener("click", () => openPicker($("output-dir"), true));
  $("picker-up").addEventListener("click", () => picker.listing && picker.listing.parent && browse(picker.listing.parent));
  $("picker-home").addEventListener("click", () => browse(""));
  $("picker-roots").addEventListener("change", (e) => browse(e.target.value));
  $("picker-cancel").addEventListener("click", () => $("picker").close());
  $("picker-choose").addEventListener("click", () => {
    if (!picker.listing) return;
    picker.field.value = picker.listing.path;
    $("picker").close();
  });
  async function makeFolder() {
    if (!picker.listing) return;
    try {
      showListing(await api("/api/mkdir", { parent: picker.listing.path, name: $("picker-new-name").value }));
      $("picker-new-name").value = "";
      setStatus($("picker-status"), "已建立資料夾。按「選擇這個資料夾」使用它。");
    } catch (err) {
      setStatus($("picker-status"), err.message, true);
    }
  }
  $("picker-mkdir").addEventListener("click", makeFolder);
  $("picker-new-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      makeFolder();
    }
  });

  api("/api/state")
    .then((s) => {
      if (s.default_input) $("input-dir").value = s.default_input;
      if (s.scanned) {
        state = s;
        render();
      }
    })
    .catch((err) => setStatus($("scan-status"), err.message, true));
})();
