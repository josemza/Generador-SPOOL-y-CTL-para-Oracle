(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function setPanelOpen(panel, open) {
    panel.dataset.open = open ? "true" : "false";
    const btn = $(".accordion-btn", panel);
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function initThemeToggle() {
    const KEY = "ui_theme";
    const btn = document.querySelector("#theme_toggle");

    function apply(theme) {
      document.documentElement.dataset.theme = theme;
      if (btn) {
        const isLight = theme === "light";
        btn.textContent = isLight ? "Modo oscuro" : "Modo claro";
        btn.setAttribute("aria-pressed", isLight ? "true" : "false");
      }
    }

    // Ajusta texto del botón según el tema ya aplicado (por el script inline en <head>)
    const current = document.documentElement.dataset.theme || "dark";
    apply(current);

    if (!btn) return;

    btn.addEventListener("click", () => {
      const now = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      localStorage.setItem(KEY, now);
      apply(now);
    });
  }

  function initAccordion() {
    const panels = $$(".panel[data-accordion]");
    panels.forEach((panel, idx) => {
      const btn = $(".accordion-btn", panel);
      if (!btn) return;

      btn.addEventListener("click", () => {
        const isOpen = panel.dataset.open === "true";
        panels.forEach(p => p !== panel && setPanelOpen(p, false));
        setPanelOpen(panel, !isOpen);
      });

      if (idx === 0) setPanelOpen(panel, true);
    });
  }

  function getFilenameFromDisposition(disposition) {
    if (!disposition) return null;
    const match = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(disposition);
    if (!match) return null;
    return decodeURIComponent(match[1].replace(/"/g, "").trim());
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "download";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function setStatus(form, kind, message) {
    const box = $(".status", form);
    if (!box) return;
    box.dataset.kind = kind;
    box.textContent = message;
  }

  function setBusy(form, busy) {
    form.dataset.busy = busy ? "true" : "false";
    const submit = $('button[type="submit"]', form);
    const reset = $('button[type="reset"]', form);
    if (submit) submit.disabled = !!busy;
    if (reset) reset.disabled = !!busy;
    $$("input, select, textarea", form).forEach(el => {
      if (el.type === "file") return;
      el.disabled = !!busy;
    });
  }

  function ensureTrailingSeparator(value) {
    if (!value) return value;
    const v = value.trim();
    const hasBack = v.includes("\\");
    const hasFwd = v.includes("/") && !hasBack;
    const sep = (hasBack || !hasFwd) ? "\\" : "/";
    if (v.endsWith("\\") || v.endsWith("/")) return v;
    return v + sep;
  }

  function initLightValidation() {
    const exportInput = $("#export_path");
    if (exportInput) {
      exportInput.addEventListener("blur", () => {
        exportInput.value = ensureTrailingSeparator(exportInput.value);
        localStorage.setItem("spool_export_path", exportInput.value);
      });
    }

    const reportInput = $("#report_name");
    if (reportInput) {
      reportInput.addEventListener("blur", () => {
        localStorage.setItem("spool_report_name", (reportInput.value || "").trim());
      });
    }
  }

  function restoreSpoolPrefs() {
    const exportInput = $("#export_path");
    const reportInput = $("#report_name");

    const savedPath = localStorage.getItem("spool_export_path");
    const savedReport = localStorage.getItem("spool_report_name");

    if (exportInput && savedPath && !exportInput.value.trim()) exportInput.value = savedPath;
    if (reportInput && savedReport && !reportInput.value.trim()) reportInput.value = savedReport;
  }

  function initSpoolModeToggle() {
    const spoolForm = $('form[action="/api/v1/spool"]');
    if (!spoolForm) return;

    const csvBlocks = $$('[data-source="csv"]', spoolForm);
    const sqlBlocks = $$('[data-source="sql"]', spoolForm);

    const fileInput = $("#spool_file", spoolForm);
    const tableInput = $("#table_name", spoolForm);
    const sqlArea = $("#sql_query", spoolForm);

    function show(el, on) {
      if (!el) return;
      el.classList.toggle("hidden", !on);
    }

    function applyMode() {
      const mode = (spoolForm.querySelector('input[name="source_mode"]:checked')?.value || "csv").toLowerCase();
      const isCsv = mode === "csv";

      csvBlocks.forEach(b => show(b, isCsv));
      sqlBlocks.forEach(b => show(b, !isCsv));

      if (fileInput) { fileInput.required = isCsv; fileInput.disabled = !isCsv; }
      if (tableInput) { tableInput.required = isCsv; tableInput.disabled = !isCsv; }
      if (sqlArea) { sqlArea.required = !isCsv; sqlArea.disabled = isCsv; }

      const fileName = $(".js-file-name", spoolForm);
      if (!isCsv && fileName) fileName.textContent = "";
    }

    $$('input[name="source_mode"]', spoolForm).forEach(r => {
      r.addEventListener("change", applyMode);
    });

    applyMode();
  }

  async function submitAsFetch(form) {
    const action = form.getAttribute("action");
    const method = (form.getAttribute("method") || "post").toUpperCase();

    const fileInput = form.querySelector('input[type="file"]');
    if (fileInput && fileInput.required && (!fileInput.files || fileInput.files.length === 0)) {
      setStatus(form, "error", "Selecciona un archivo para continuar.");
      return;
    }

    const sqlArea = form.querySelector("#sql_query");
    if (sqlArea && !sqlArea.disabled && sqlArea.required && !String(sqlArea.value || "").trim()) {
      setStatus(form, "error", "Ingresa una consulta SQL para continuar.");
      return;
    }

    const exportPath = form.querySelector("#export_path");
    if (exportPath) exportPath.value = ensureTrailingSeparator(exportPath.value);

    const fd = new FormData(form);

    setBusy(form, true);
    setStatus(form, "info", "Procesando. Por favor, no cierres esta pestaña.");

    try {
      const res = await fetch(action, { method, body: fd });

      if (!res.ok) {
        let detail = "";
        const contentType = res.headers.get("content-type") || "";
        if (contentType.includes("application/json")) {
          const j = await res.json().catch(() => null);
          detail = j?.detail
            ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail))
            : JSON.stringify(j);
        } else {
          detail = await res.text().catch(() => "");
        }
        setStatus(form, "error", `Error (${res.status}). ${detail || "Revisa los parámetros y vuelve a intentar."}`);
        return;
      }

      const disposition = res.headers.get("content-disposition");
      const filename = getFilenameFromDisposition(disposition) || "archivo_generado";

      const blob = await res.blob();
      downloadBlob(blob, filename);

      setStatus(form, "ok", "Listo. El archivo se descargó correctamente.");
    } catch (err) {
      setStatus(form, "error", `Error inesperado. ${err?.message || String(err)}`);
    } finally {
      setBusy(form, false);
    }
  }

  function showPreview(form, on) {
    const wrap = form.querySelector(".preview-wrap");
    if (!wrap) return;
    wrap.classList.toggle("hidden", !on);
  }

  function renderPreviewTable(form, payload) {
    const table = form.querySelector(".preview-table");
    if (!table) return;

    const cols = payload.columns || [];
    const rows = payload.rows || [];

    if (!cols.length) {
      table.innerHTML = "<tbody><tr><td>No se detectaron columnas.</td></tr></tbody>";
      return;
    }

    const thead = `
      <thead>
        <tr>${cols.map(c => `<th>${escapeHtml(String(c))}</th>`).join("")}</tr>
      </thead>
    `;

    const tbodyRows = rows.map(r => {
      const cells = cols.map((_, i) => {
        const v = (r && r.length > i) ? r[i] : "";
        return `<td>${escapeHtml(v == null ? "" : String(v))}</td>`;
      }).join("");
      return `<tr>${cells}</tr>`;
    }).join("");

    const tbody = `<tbody>${tbodyRows || `<tr><td colspan="${cols.length}">Sin filas para mostrar.</td></tr>`}</tbody>`;
    table.innerHTML = thead + tbody;
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (m) => (
      m === "&" ? "&amp;" :
      m === "<" ? "&lt;" :
      m === ">" ? "&gt;" :
      m === '"' ? "&quot;" : "&#039;"
    ));
  }

  async function requestPreview(form) {
    const fileInput = form.querySelector('input[type="file"]');
    if (fileInput && fileInput.required && (!fileInput.files || fileInput.files.length === 0)) {
      setStatus(form, "error", "Selecciona un archivo para continuar.");
      return;
    }

    const sqlArea = form.querySelector("#sql_query");
    if (sqlArea && !sqlArea.disabled && sqlArea.required && !String(sqlArea.value || "").trim()) {
      setStatus(form, "error", "Ingresa una consulta SQL para continuar.");
      return;
    }

    const fd = new FormData(form);

    // toma el selector del UI si existe
    const previewSel = form.querySelector("#preview_rows");
    const n = previewSel ? String(previewSel.value || "10") : "10";
    fd.set("preview_rows", n);

    setBusy(form, true);
    setStatus(form, "info", "Generando preview…");
    showPreview(form, false);

    try {
      const res = await fetch("/api/v1/spool/preview", { method: "POST", body: fd });

      if (!res.ok) {
        const contentType = res.headers.get("content-type") || "";
        let detail = "";
        if (contentType.includes("application/json")) {
          const j = await res.json().catch(() => null);
          detail = j?.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : JSON.stringify(j);
        } else {
          detail = await res.text().catch(() => "");
        }
        setStatus(form, "error", `Error (${res.status}). ${detail || "No se pudo generar el preview."}`);
        return;
      }

      const payload = await res.json();
      renderPreviewTable(form, payload);
      showPreview(form, true);
      setStatus(form, "ok", `Preview listo (${payload.row_count || 0} filas).`);
    } catch (err) {
      setStatus(form, "error", `Error inesperado. ${err?.message || String(err)}`);
    } finally {
      setBusy(form, false);
    }
  }

    function initForms() {
      const forms = $$("form[data-enhanced]");
      forms.forEach(form => {
        form.addEventListener("submit", (e) => {
          e.preventDefault();
          submitAsFetch(form);
        });

        form.addEventListener("reset", () => {
          setStatus(form, "info", "");
          const box = $(".status", form);
          if (box) {
            box.dataset.kind = "";
            box.textContent = "";
          }

          const wrap = form.querySelector(".preview-wrap");
          if (wrap) wrap.classList.add("hidden");

          const table = form.querySelector(".preview-table");
          if (table) table.innerHTML = "";

          const fileName = form.querySelector(".js-file-name");
          if (fileName) fileName.textContent = "";
        });

        const fileInput = $('input[type="file"]', form);
        const fileName = $(".js-file-name", form);
        if (fileInput && fileName) {
          fileInput.addEventListener("change", () => {
            const f = fileInput.files && fileInput.files[0];
            fileName.textContent = f ? `Archivo: ${f.name}` : "";
          });
        }

        const previewBtn = form.querySelector("button[data-preview]");
        if (previewBtn) {
          previewBtn.addEventListener("click", () => requestPreview(form));
        }
      });
    }

    function initSpoolHelpModal() {
      const openBtn = document.querySelector("#openSpoolHelpPill, #openSpoolHelp");
      const modal = document.querySelector("#spoolHelpModal");
      if (!openBtn || !modal) return;

      const closeBtns = $$('[data-modal-close]', modal);
      const btnCancel = modal.querySelector('[data-modal-cancel]');

      function openModal() {
        modal.classList.remove('hidden');
        setTimeout(() => {
          const focusEl = modal.querySelector('.icon-btn[data-modal-close]') || modal.querySelector('.modal-card');
          if (focusEl && focusEl.focus) focusEl.focus();
        }, 0);
        document.addEventListener('keydown', onKeydown);
      }

      function closeModal() {
        modal.classList.add('hidden');
        document.removeEventListener('keydown', onKeydown);
        openBtn.focus();
      }

      function onKeydown(e) {
        if (e.key === 'Escape') {
          e.preventDefault();
          closeModal();
        }
      }

      openBtn.addEventListener('click', openModal);
      closeBtns.forEach(b => b.addEventListener('click', closeModal));
      if (btnCancel) btnCancel.addEventListener('click', closeModal);
    }

    function initCtlHelpModal() {
      const trigger = document.querySelector("#openCtlHelpPill");
      const modal = document.querySelector("#ctlHelpModal");
      if (!trigger || !modal) return;

      const closeBtns = $$('[data-modal-close]', modal);
      const btnCancel = modal.querySelector('[data-modal-cancel]');

      function openModal() {
        modal.classList.remove('hidden');
        setTimeout(() => {
          const focusEl = modal.querySelector('.icon-btn[data-modal-close]') || modal.querySelector('.modal-card');
          if (focusEl && focusEl.focus) focusEl.focus();
        }, 0);
        document.addEventListener('keydown', onKeydown);
      }

      function closeModal() {
        modal.classList.add('hidden');
        document.removeEventListener('keydown', onKeydown);
        trigger.focus();
      }

      function onKeydown(e) {
        if (e.key === 'Escape') {
          e.preventDefault();
          closeModal();
        }
      }

      trigger.addEventListener('click', openModal);
      closeBtns.forEach(b => b.addEventListener('click', closeModal));
      if (btnCancel) btnCancel.addEventListener('click', closeModal);
    }

    function initPathModal() {
    const browseBtn = document.querySelector("[data-browse-path]");
    const exportInput = document.querySelector("#export_path");

    const modal = document.querySelector("#pathModal");
    if (!browseBtn || !exportInput || !modal) return;

    const rootSel = modal.querySelector("#path_root");
    const currentInput = modal.querySelector("#path_current");
    const listBox = modal.querySelector("#path_list");
    const statusEl = modal.querySelector("[data-path-status]");
    const btnUp = modal.querySelector("[data-path-up]");
    const btnGo = modal.querySelector("[data-path-go]");
    const btnSelect = modal.querySelector("[data-path-select]");
    const btnCancel = modal.querySelector("[data-modal-cancel]");
    const closeBtns = $$("#pathModal [data-modal-close]");

    let currentPath = "";
    let selected = null; // {name, path, denied}

    function setModalStatus(msg) {
      if (!statusEl) return;
      statusEl.textContent = msg || "";
    }

    function openModal() {
      modal.classList.remove("hidden");
      setModalStatus("Cargando carpetas…");
      selected = null;
      listBox.innerHTML = "";
      loadRoots().catch(err => setModalStatus(err?.message || String(err)));
      // foco inicial
      setTimeout(() => currentInput?.focus(), 0);
      document.addEventListener("keydown", onKeydown);
    }

    function closeModal() {
      modal.classList.add("hidden");
      document.removeEventListener("keydown", onKeydown);
      setModalStatus("");
      selected = null;
      browseBtn.focus();
    }

    function onKeydown(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        closeModal();
      }
    }

    async function loadRoots() {
      const res = await fetch("/api/v1/fs/roots");
      if (!res.ok) throw new Error("No se pudieron cargar las raíces.");
      const roots = await res.json();

      rootSel.innerHTML = roots.map(r => `<option value="${escapeHtml(r.path)}">${escapeHtml(r.label)}</option>`).join("");
      const initial = roots[0]?.path || "";
      if (!initial) {
        setModalStatus("No se detectaron raíces para explorar.");
        return;
      }
      rootSel.value = initial;
      await listPath(initial);
      setModalStatus("");
    }

    async function listPath(path) {
      setModalStatus("Listando…");
      selected = null;

      const url = `/api/v1/fs/list?path=${encodeURIComponent(path)}`;
      const res = await fetch(url);
      if (!res.ok) {
        const contentType = res.headers.get("content-type") || "";
        let detail = "";
        if (contentType.includes("application/json")) {
          const j = await res.json().catch(() => null);
          detail = j?.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : "Error.";
        } else {
          detail = await res.text().catch(() => "Error.");
        }
        throw new Error(detail || `Error (${res.status}).`);
      }

      const payload = await res.json();
      currentPath = payload.path || path;
      if (currentInput) currentInput.value = currentPath;

      const folders = payload.folders || [];
      if (!folders.length) {
        listBox.innerHTML = `<div class="path-item"><span>(Sin subcarpetas)</span></div>`;
      } else {
        listBox.innerHTML = folders.map(f => {
          const cls = `path-item${f.denied ? " is-denied" : ""}`;
          return `<div class="${cls}" data-path="${escapeHtml(f.path)}" data-denied="${f.denied ? "1" : "0"}">
              <span>${escapeHtml(f.name)}</span>
              <span class="small">${f.denied ? "Restringido" : ""}</span>
          </div>`;
        }).join("");
      }

      // guardar parent en el botón Arriba
      btnUp.dataset.parent = payload.parent || "";
      btnUp.disabled = !payload.parent;

      setModalStatus("");
    }

    function selectRow(rowEl) {
      if (!rowEl) return;
      const denied = rowEl.getAttribute("data-denied") === "1";
      if (denied) return;

      $$(".path-item", listBox).forEach(x => x.classList.remove("is-selected"));
      rowEl.classList.add("is-selected");

      selected = {
        name: rowEl.textContent || "",
        path: rowEl.getAttribute("data-path") || "",
        denied: false
      };
    }

    // Eventos
    browseBtn.addEventListener("click", openModal);

    rootSel.addEventListener("change", async () => {
      const p = rootSel.value;
      try { await listPath(p); } catch (e) { setModalStatus(e?.message || String(e)); }
    });

    btnGo.addEventListener("click", async () => {
      const p = (currentInput.value || "").trim();
      if (!p) return;
      try { await listPath(p); } catch (e) { setModalStatus(e?.message || String(e)); }
    });

    btnUp.addEventListener("click", async () => {
      const parent = btnUp.dataset.parent || "";
      if (!parent) return;
      try { await listPath(parent); } catch (e) { setModalStatus(e?.message || String(e)); }
    });

    listBox.addEventListener("click", (e) => {
      const row = e.target.closest(".path-item");
      if (!row) return;
      selectRow(row);
    });

    listBox.addEventListener("dblclick", async (e) => {
      const row = e.target.closest(".path-item");
      if (!row) return;
      const denied = row.getAttribute("data-denied") === "1";
      if (denied) return;
      const p = row.getAttribute("data-path");
      if (!p) return;
      try { await listPath(p); } catch (err) { setModalStatus(err?.message || String(err)); }
    });

    btnSelect.addEventListener("click", () => {
      // Si el usuario no selecciona subcarpeta, usamos la ruta actual
      const p = ensureTrailingSeparator((currentInput.value || "").trim());
      if (!p) return;

      exportInput.value = p;
      localStorage.setItem("spool_export_path", p);
      closeModal();
    });

    btnCancel.addEventListener("click", closeModal);
    closeBtns.forEach(b => b.addEventListener("click", closeModal));
  }

  document.addEventListener("DOMContentLoaded", () => {
    initThemeToggle();
    initAccordion();
    restoreSpoolPrefs();
    initLightValidation();
    initSpoolModeToggle();
    initForms();
    initPathModal();
    initSpoolHelpModal();
    initCtlHelpModal();
  });
})();
