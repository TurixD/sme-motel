/* inventario.js - Fase 5a */

/* ── Toasts ──────────────────────────────────────────────── */
function toast(msg, tipo = "success") {
    const c = document.getElementById("toast-container");
    const el = document.createElement("div");
    el.className = `toast toast--${tipo}`;
    el.textContent = msg;
    c.appendChild(el);
    requestAnimationFrame(() => {
        requestAnimationFrame(() => el.classList.add("toast--show"));
    });
    setTimeout(() => {
        el.classList.remove("toast--show");
        setTimeout(() => el.remove(), 400);
    }, 3200);
}

/* ── Modales ──────────────────────────────────────────────── */
function openModal(id) {
    document.getElementById(id).removeAttribute("hidden");
}

function closeModal(id) {
    document.getElementById(id).setAttribute("hidden", "");
}

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        document.querySelectorAll(".modal:not([hidden])").forEach((m) =>
            m.setAttribute("hidden", "")
        );
    }
});

/* ── Estado global ─────────────────────────────────────────── */
let _editandoId = null;
let _historialId = null;
let _historialOffset = 0;
let _historialTotal = 0;

/* ── Modal agregar / editar producto ───────────────────────── */
function abrirModalAgregar() {
    _editandoId = null;
    document.getElementById("modal-producto-title").textContent = "Agregar producto";
    document.getElementById("form-producto").reset();
    document.getElementById("btn-guardar-producto").textContent = "Agregar";
    openModal("modal-producto");
    document.getElementById("inp-nombre").focus();
}

function abrirModalEditar(id) {
    const row = document.querySelector(`tr[data-id="${id}"]`);
    _editandoId = id;
    document.getElementById("modal-producto-title").textContent = "Editar producto";
    document.getElementById("inp-nombre").value = row.dataset.nombre || "";
    document.getElementById("inp-proveedor").value = row.dataset.proveedor || "";
    document.getElementById("inp-unidad").value = row.dataset.unidad || "";
    document.getElementById("inp-stock-minimo").value = row.dataset.stockMinimo || "0";
    document.getElementById("btn-guardar-producto").textContent = "Guardar cambios";
    openModal("modal-producto");
    document.getElementById("inp-nombre").focus();
}

async function guardarProducto() {
    const nombre = document.getElementById("inp-nombre").value.trim();
    if (!nombre) {
        toast("El nombre es requerido", "error");
        return;
    }
    const payload = {
        nombre,
        proveedor_default: document.getElementById("inp-proveedor").value.trim(),
        unidad: document.getElementById("inp-unidad").value.trim(),
        stock_minimo: parseFloat(document.getElementById("inp-stock-minimo").value) || 0,
    };

    const url = _editandoId
        ? `/inventario/productos/${_editandoId}`
        : "/inventario/productos";
    const method = _editandoId ? "PUT" : "POST";

    const btn = document.getElementById("btn-guardar-producto");
    btn.disabled = true;
    try {
        const r = await fetch(url, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        const data = await r.json();
        if (!data.ok) {
            toast(data.error || "Error", "error");
            return;
        }
        closeModal("modal-producto");
        toast(_editandoId ? "Producto actualizado" : "Producto agregado", "success");
        setTimeout(() => location.reload(), 600);
    } catch {
        toast("Error de conexión", "error");
    } finally {
        btn.disabled = false;
    }
}

/* ── Eliminar producto ─────────────────────────────────────── */
let _eliminandoId = null;

function confirmarEliminar(id) {
    _eliminandoId = id;
    const row = document.querySelector(`tr[data-id="${id}"]`);
    document.getElementById("modal-eliminar-nombre").textContent = row.dataset.nombre || "";
    document.getElementById("modal-eliminar-aviso").setAttribute("hidden", "");
    openModal("modal-eliminar");
}

async function ejecutarEliminar(accion) {
    if (!_eliminandoId) return;
    const btn = document.getElementById(`btn-${accion}`);
    if (btn) btn.disabled = true;

    try {
        const r = await fetch(
            `/inventario/productos/${_eliminandoId}?accion=${accion}`,
            { method: "DELETE" }
        );
        const data = await r.json();

        if (data.tiene_historial && accion === "eliminar") {
            document.getElementById("modal-eliminar-aviso").removeAttribute("hidden");
            if (btn) btn.disabled = false;
            return;
        }
        if (!data.ok) {
            toast(data.error || "Error", "error");
            if (btn) btn.disabled = false;
            return;
        }
        closeModal("modal-eliminar");
        toast(
            accion === "desactivar" ? "Producto desactivado" : "Producto eliminado",
            "success"
        );
        setTimeout(() => location.reload(), 600);
    } catch {
        toast("Error de conexión", "error");
        if (btn) btn.disabled = false;
    }
}

/* ── Historial de movimientos ──────────────────────────────── */
async function verHistorial(id) {
    _historialId = id;
    _historialOffset = 0;
    _historialTotal = 0;
    document.getElementById("historial-body").innerHTML =
        '<tr><td colspan="5" class="text-muted" style="text-align:center;padding:1.5rem">Cargando...</td></tr>';
    document.getElementById("ver-mas-wrap").setAttribute("hidden", "");
    openModal("modal-historial");
    await _cargarHistorial(true);
}

async function _cargarHistorial(reemplazar) {
    try {
        const r = await fetch(
            `/inventario/productos/${_historialId}/movimientos?offset=${_historialOffset}`
        );
        const data = await r.json();
        if (!data.ok) {
            toast("Error cargando historial", "error");
            return;
        }
        document.getElementById("modal-historial-title").textContent =
            `Historial — ${data.producto.nombre}`;
        _historialTotal = data.total;

        const tbody = document.getElementById("historial-body");
        if (reemplazar) tbody.innerHTML = "";

        if (data.items.length === 0 && reemplazar) {
            tbody.innerHTML =
                '<tr><td colspan="5" class="text-muted" style="text-align:center;padding:1.5rem">Sin movimientos registrados</td></tr>';
        } else {
            data.items.forEach((it) => {
                const tr = document.createElement("tr");
                const tipoClass = `tipo-${it.tipo}`;
                const cantFmt = (it.tipo === "salida" ? "−" : "+") + it.cantidad;
                const cantColor =
                    it.tipo === "salida"
                        ? "color:var(--accent-expense)"
                        : it.tipo === "entrada"
                        ? "color:var(--accent-income)"
                        : "color:var(--accent-inventory)";
                tr.innerHTML = `
                    <td>${it.fecha}</td>
                    <td><span class="tipo-badge ${tipoClass}">${it.tipo}</span></td>
                    <td style="font-family:var(--font-mono);${cantColor}">${it.tipo === "conteo" ? it.cantidad : cantFmt}</td>
                    <td>${it.descripcion || "—"}</td>
                    <td class="text-muted">${it.origen || "—"}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        _historialOffset += data.items.length;
        const verMas = document.getElementById("ver-mas-wrap");
        if (data.hay_mas) {
            verMas.removeAttribute("hidden");
        } else {
            verMas.setAttribute("hidden", "");
        }
    } catch {
        toast("Error de conexión", "error");
    }
}

function cargarMasHistorial() {
    _cargarHistorial(false);
}

/* ── Lista de compra (modal, solo sábados) ─────────────────── */
let _comprasData = null;

function abrirListaCompra() {
    openModal("modal-compras");
    if (!_comprasData) _cargarCompras();
}

function _fmtNum(n) {
    // 9.0 → "9", 2.5 → "2.5"
    return Number.isInteger(n) ? String(n) : String(Math.round(n * 10) / 10);
}

async function _cargarCompras() {
    try {
        const r = await fetch("/inventario/api/compras");
        const data = await r.json();
        if (!data.ok) return;
        _comprasData = data;
        _renderCompras(data);
        const badge = document.getElementById("compras-count");
        if (badge) badge.textContent = data.total > 0 ? String(data.total) : "";
    } catch {
        const cont = document.getElementById("compras-contenido");
        if (cont)
            cont.innerHTML =
                '<div class="compras-vacio compras-vacio--error">Error al cargar la lista</div>';
    }
}

function _renderCompras(data) {
    const cont = document.getElementById("compras-contenido");
    const resumen = document.getElementById("compras-resumen");
    const btnCopiar = document.getElementById("btn-copiar-compras");
    const btnPdf = document.getElementById("btn-pdf-compras");
    if (!cont) return;

    if (!data.total) {
        cont.innerHTML =
            '<div class="compras-vacio compras-vacio--ok">' +
            '<span class="compras-vacio__check">✓</span>' +
            "Todo el inventario está por encima del mínimo.</div>";
        if (resumen) resumen.textContent = "Nada por comprar 🎉";
        if (btnCopiar) btnCopiar.setAttribute("hidden", "");
        if (btnPdf) btnPdf.setAttribute("hidden", "");
        return;
    }

    if (resumen) {
        const nProv = data.grupos.length;
        resumen.textContent =
            `${data.total} ${data.total === 1 ? "producto" : "productos"} por surtir` +
            ` · ${nProv} ${nProv === 1 ? "proveedor" : "proveedores"}`;
    }
    if (btnCopiar) btnCopiar.removeAttribute("hidden");
    if (btnPdf) btnPdf.removeAttribute("hidden");

    let html = "";
    data.grupos.forEach((g) => {
        const n = g.items.length;
        html +=
            '<div class="compras-grupo">' +
            '<div class="compras-grupo__head">' +
            `<span class="compras-grupo__prov">${_escMatch(g.proveedor)}</span>` +
            `<span class="compras-grupo__count">${n} ${n === 1 ? "producto" : "productos"}</span>` +
            "</div>" +
            '<ul class="compras-lista">';
        g.items.forEach((it) => {
            const unidad = it.unidad ? ` ${_escMatch(it.unidad)}` : "";
            const est = it.fuente === "estimado" ? '<span class="compras-item__est" title="Cantidad estimada (aún sin historial propio de conteos)">*</span>' : "";
            html +=
                '<li class="compras-item">' +
                '<div class="compras-item__info">' +
                `<span class="compras-item__nombre">${_escMatch(it.nombre)}${est}</span>` +
                `<span class="compras-item__stock">tienes ${_fmtNum(it.stock_actual)} · mín ${_fmtNum(it.stock_minimo)}</span>` +
                "</div>" +
                `<span class="compras-item__sugerido">+${_fmtNum(it.sugerido)}${unidad}</span>` +
                "</li>";
        });
        html += "</ul></div>";
    });
    if (data.n_estimados) {
        html +=
            '<p class="compras-nota">* Cantidad estimada con el consumo promedio del negocio ' +
            "(aún sin historial propio). Se afina conforme registres más conteos.</p>";
    }
    cont.innerHTML = html;
}

function copiarListaCompra() {
    if (!_comprasData || !_comprasData.total) return;
    const lineas = ["🛒 Lista de compra — SME", ""];
    _comprasData.grupos.forEach((g) => {
        lineas.push(`— ${g.proveedor} —`);
        g.items.forEach((it) => {
            const unidad = it.unidad ? ` ${it.unidad}` : "";
            lineas.push(`  • ${it.nombre}: ${_fmtNum(it.sugerido)}${unidad}`);
        });
        lineas.push("");
    });
    const texto = lineas.join("\n").trim();
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(texto).then(
            () => toast("Lista copiada", "success"),
            () => toast("No se pudo copiar", "error")
        );
    } else {
        toast("Copiar no disponible en este navegador", "error");
    }
}

/* ── Tabs (Sub-fase 5C) ────────────────────────────────────── */
let _catalogoInventario = null;
let _matchesData = [];

function _initTabs() {
    document.querySelectorAll(".inv-tab").forEach((btn) => {
        btn.addEventListener("click", function () {
            document.querySelectorAll(".inv-tab").forEach((b) => b.classList.remove("inv-tab--active"));
            this.classList.add("inv-tab--active");
            document.querySelectorAll(".tab-content").forEach((el) => (el.hidden = true));
            const target = document.getElementById("tab-" + this.dataset.tab);
            if (target) target.hidden = false;
            if (this.dataset.tab === "matches") _cargarMatches();
        });
    });

    const searchInp = document.getElementById("matches-search");
    if (searchInp) {
        searchInp.addEventListener("input", function () {
            const q = this.value.toLowerCase();
            const filtrado = _matchesData.filter(
                (m) => m.sku_sams.toLowerCase().includes(q) || m.texto_ticket.toLowerCase().includes(q)
            );
            _renderMatches(filtrado);
        });
    }
}

async function _cargarMatches() {
    const tbody = document.getElementById("matches-tbody");
    if (!tbody) return;
    tbody.innerHTML =
        '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--text-tertiary)">Cargando…</td></tr>';

    try {
        if (!_catalogoInventario) {
            const r = await fetch("/inventario/api/stock");
            _catalogoInventario = (await r.json()).map((p) => ({ id: p.id, nombre: p.nombre }));
        }
        const r2 = await fetch("/inventario/api/matches");
        _matchesData = await r2.json();
        _renderMatches(_matchesData);

        const badge = document.getElementById("matches-count");
        if (badge) badge.textContent = _matchesData.length > 0 ? String(_matchesData.length) : "";
    } catch {
        if (tbody)
            tbody.innerHTML =
                '<tr><td colspan="5" style="text-align:center;color:var(--accent-expense)">Error al cargar</td></tr>';
    }
}

function _renderMatches(data) {
    const tbody = document.getElementById("matches-tbody");
    if (!tbody) return;
    if (!data.length) {
        tbody.innerHTML =
            '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--text-tertiary)">Sin matches aprendidos todavía</td></tr>';
        return;
    }

    tbody.innerHTML = "";
    const catalog = _catalogoInventario || [];

    data.forEach((m) => {
        const tr = document.createElement("tr");

        let opts = "";
        catalog.forEach((c) => {
            opts += `<option value="${c.id}"${c.id === m.inventario_id ? " selected" : ""}>${_escMatch(c.nombre)}</option>`;
        });

        tr.innerHTML = `
            <td class="matches-sku">${_escMatch(m.sku_sams)}</td>
            <td class="matches-texto" title="${_escMatch(m.texto_ticket)}">${_escMatch(m.texto_ticket)}</td>
            <td><select class="field-input field-input--sm match-inv-sel" style="min-width:180px">${opts}</select></td>
            <td class="text-right text-muted" title="Primera vez: ${_escMatch(m.primera_vez || '')}\nÚltima vez: ${_escMatch(m.ultima_vez || '')}">${m.veces_confirmado}</td>
            <td class="text-right">
                <button class="btn-icon btn-icon--danger match-del-btn" title="Borrar match" data-match-id="${m.id}" data-sku="${_escMatch(m.sku_sams)}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"/>
                        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                        <path d="M10 11v6"/><path d="M14 11v6"/>
                        <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                    </svg>
                </button>
            </td>
        `;

        const sel = tr.querySelector(".match-inv-sel");
        let invIdActual = m.inventario_id;
        sel.addEventListener("change", async function () {
            const nuevoId = parseInt(this.value, 10);
            if (nuevoId === invIdActual) return;
            const oldNombre = catalog.find((c) => c.id === invIdActual)?.nombre || "(anterior)";
            const newNombre = catalog.find((c) => c.id === nuevoId)?.nombre || "(nuevo)";
            if (!confirm(`¿Cambiar match del SKU ${m.sku_sams} de "${oldNombre}" a "${newNombre}"?`)) {
                this.value = invIdActual;
                return;
            }
            try {
                const r = await fetch(`/inventario/api/matches/${m.id}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ inventario_id: nuevoId }),
                });
                const res = await r.json();
                if (res.ok) {
                    invIdActual = nuevoId;
                    m.inventario_id = nuevoId;
                    toast("Match actualizado", "success");
                } else {
                    this.value = invIdActual;
                    toast(res.error || "Error al actualizar", "error");
                }
            } catch {
                this.value = invIdActual;
                toast("Error de conexión", "error");
            }
        });

        const delBtn = tr.querySelector(".match-del-btn");
        delBtn.addEventListener("click", async function () {
            const matchId = parseInt(this.dataset.matchId, 10);
            const sku = this.dataset.sku;
            if (!confirm(`¿Borrar el match aprendido para SKU ${sku}?\nEn el próximo ticket, este producto volverá a pedirse a la IA.`)) return;
            try {
                const r = await fetch(`/inventario/api/matches/${matchId}`, { method: "DELETE" });
                const res = await r.json();
                if (res.ok) {
                    toast("Match borrado", "success");
                    _cargarMatches();
                } else {
                    toast(res.error || "Error al borrar", "error");
                }
            } catch {
                toast("Error de conexión", "error");
            }
        });

        tbody.appendChild(tr);
    });
}

function _escMatch(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* ── Init ──────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
    // Cerrar modales al click en backdrop
    document.querySelectorAll(".modal__backdrop").forEach((bd) => {
        bd.addEventListener("click", () => {
            const modal = bd.closest(".modal");
            if (modal) modal.setAttribute("hidden", "");
        });
    });

    // Formulario producto con Enter
    document.getElementById("form-producto")?.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") {
            e.preventDefault();
            guardarProducto();
        }
    });

    _initTabs();
    // Precargar la lista de compra solo si el botón del sábado está presente,
    // para mostrar el contador y que el pop-up abra al instante.
    if (document.getElementById("btn-abrir-compras")) _cargarCompras();
});
