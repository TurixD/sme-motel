/* cortes.js — Lógica de modales para /cortes (v2.3)
   FIX1: dropdown cargado por JS según asignaciones del turno
   FIX2: sueldo tarde usa empleados únicos (sin duplicar doble turno)
   FIX3: ventanas horarias en UI (backend también las valida) */

(function () {
    var DATOS     = window.CORTES_DATA || {};
    var empleados = DATOS.empleados   || [];   // todos los activos con .sueldo
    var asigs     = DATOS.asignaciones || {};  // {turno: [{empleado_id, emp_nombre, sueldo}]}
    var sueldos   = DATOS.sueldos     || {};   // {turno: monto} — fallback
    var hoy       = DATOS.hoy         || '';
    var esAdmin   = DATOS.es_admin    || false;

    // ── Utilidades ──────────────────────────────────────────

    function fmt(n) {
        var num = parseFloat(n) || 0;
        return '$' + num.toLocaleString('es-MX', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    }

    function showError(el, msg) { el.textContent = msg; el.hidden = false; }
    function hideError(el)      { el.hidden = true; el.textContent = ''; }

    function postJSON(url, body) {
        return fetch(url, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
            body:    JSON.stringify(body),
        }).then(function (r) { return r.json(); });
    }

    function setOptionByValue(sel, val) {
        var v = String(val);
        for (var i = 0; i < sel.options.length; i++) {
            if (sel.options[i].value === v) { sel.selectedIndex = i; return true; }
        }
        return false;
    }

    function getSelectedEmpSueldo(sel) {
        var opt = sel.options[sel.selectedIndex];
        return opt ? (parseFloat(opt.dataset.sueldo) || 0) : 0;
    }

    // ── FIX 1: poblar dropdown con empleados del turno (o todos si no hay asignación) ──

    function poblarDropdown(sel, turno) {
        var asigTurno = asigs[turno] || [];
        var lista, labelPrefix;

        if (asigTurno.length > 0) {
            lista = asigTurno.map(function (a) {
                return { id: a.empleado_id, nombre: a.emp_nombre, sueldo: a.sueldo };
            });
            labelPrefix = '';
        } else {
            // Sin asignación: mostrar todos los activos
            lista = empleados.map(function (e) {
                return { id: e.id, nombre: e.nombre, sueldo: e.sueldo };
            });
            labelPrefix = '(sin asignación) ';
        }

        sel.innerHTML = '<option value="">— ' + labelPrefix + 'seleccionar —</option>';
        lista.forEach(function (e) {
            var opt = document.createElement('option');
            opt.value = e.id;
            opt.textContent = e.nombre;
            opt.dataset.sueldo = e.sueldo;
            sel.appendChild(opt);
        });

        // Auto-seleccionar si hay exactamente uno
        if (lista.length === 1) sel.selectedIndex = 1;
    }

    // ── FIX 2: sueldo del día con empleados únicos (evita doble turno duplicado) ──

    function calcSueldosDia() {
        var seen   = {};
        var total  = 0;
        var partes = [];

        ['manana', 'tarde', 'noche'].forEach(function (t) {
            (asigs[t] || []).forEach(function (emp) {
                if (!seen[emp.empleado_id]) {
                    seen[emp.empleado_id] = true;
                    total += emp.sueldo;
                    partes.push(emp.emp_nombre + ' ' + fmt(emp.sueldo));
                }
            });
        });

        // Fallback si no hay ninguna asignación: sumar por turno sin deduplicar
        if (partes.length === 0) {
            total  = (sueldos['manana'] || 0) + (sueldos['tarde'] || 0) + (sueldos['noche'] || 0);
            partes = [
                'Mañana '  + fmt(sueldos['manana'] || 0),
                'Tarde '   + fmt(sueldos['tarde']  || 0),
                'Noche '   + fmt(sueldos['noche']  || 0),
            ];
        }

        return { total: total, partes: partes };
    }

    // ── MODAL DECLARAR ───────────────────────────────────────

    var modalDec        = document.getElementById('modal-declarar');
    var decEmpId        = document.getElementById('dec-emp-id');
    var decBruto        = document.getElementById('dec-bruto');
    var decNotas        = document.getElementById('dec-notas');
    var decBrutoCalc    = document.getElementById('dec-bruto-calc');
    var decError        = document.getElementById('modal-dec-error');
    var decInfoBox      = document.getElementById('dec-info-sueldos');
    var decInfoSueldo   = document.getElementById('dec-info-sueldo-emp');
    var decInfoNeto     = document.getElementById('dec-info-neto');
    var decInfoNota     = document.getElementById('dec-info-nota');

    var decTurnoActual = '';
    var decFechaActual = '';   // fecha real del turno (para noche = día anterior; mañana/tarde = hoy)

    function actualizarInfoSueldos() {
        var bruto  = parseFloat(decBruto.value) || 0;
        var sueldo = 0;
        var nota   = '';

        if (decTurnoActual === 'tarde') {
            var dia = calcSueldosDia();
            sueldo  = dia.total;
            nota    = dia.partes.join(' · ');
            decInfoSueldo.textContent = fmt(sueldo) + ' (empleados únicos del día)';
        } else {
            sueldo = getSelectedEmpSueldo(decEmpId);
            if (!sueldo) sueldo = sueldos[decTurnoActual] || 0;
            decInfoSueldo.textContent = fmt(sueldo);
        }

        decInfoNeto.textContent = fmt(bruto - sueldo);
        if (decInfoNota) decInfoNota.textContent = nota;
        decInfoBox.hidden = (sueldo === 0 && !nota);
    }

    function abrirModalDeclarar(turno, fecha) {
        decTurnoActual = turno;
        decFechaActual = fecha;   // guardar la fecha del turno para el submit (evita off-by-one en noche)
        var titulos = { manana: 'Declarar corte Mañana', tarde: 'Declarar corte Tarde', noche: 'Declarar corte Noche' };
        document.getElementById('modal-dec-titulo').textContent = titulos[turno] || 'Declarar corte';

        decBruto.value = '';
        decNotas.value = '';
        decBrutoCalc.textContent = 'Calculando...';
        decInfoBox.hidden = true;
        hideError(decError);

        // FIX 1: poblar dropdown con empleados del turno
        poblarDropdown(decEmpId, turno);

        // Calcular bruto desde API
        fetch('/cortes/api/calcular_bruto/' + turno + '/' + fecha, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.ok) {
                    decBrutoCalc.textContent = fmt(d.bruto_calculado);
                    if (!decBruto.value) {
                        decBruto.value = (d.bruto_calculado || 0).toFixed(2);
                    }
                    actualizarInfoSueldos();
                } else {
                    decBrutoCalc.textContent = 'No disponible';
                }
            })
            .catch(function () { decBrutoCalc.textContent = 'Error'; });

        modalDec.hidden = false;
    }

    document.querySelectorAll('.btn-declarar').forEach(function (btn) {
        btn.addEventListener('click', function () {
            abrirModalDeclarar(btn.dataset.turno, btn.dataset.fecha || hoy);
        });
    });

    if (decEmpId)  decEmpId.addEventListener('change', actualizarInfoSueldos);
    if (decBruto)  decBruto.addEventListener('input',  actualizarInfoSueldos);

    var btnCancelarDec = document.getElementById('btn-cancelar-declarar');
    if (btnCancelarDec) btnCancelarDec.addEventListener('click', function () { modalDec.hidden = true; });
    if (modalDec) modalDec.addEventListener('click', function (e) { if (e.target === modalDec) modalDec.hidden = true; });

    var btnSubmitDec = document.getElementById('btn-submit-declarar');
    if (btnSubmitDec) {
        btnSubmitDec.addEventListener('click', function () {
            hideError(decError);
            var empId = parseInt(decEmpId.value);
            var bruto = parseFloat(decBruto.value);
            if (!empId)                    { showError(decError, 'Selecciona un empleado.'); return; }
            if (isNaN(bruto) || bruto < 0) { showError(decError, 'Ingresa un bruto válido.'); return; }

            btnSubmitDec.disabled    = true;
            btnSubmitDec.textContent = 'Guardando...';

            postJSON('/cortes/api/declarar', {
                turno:           decTurnoActual,
                fecha:           decFechaActual || hoy,   // fecha real del turno (noche = día anterior)
                empleado_id:     empId,
                bruto_declarado: bruto,
                notas:           (decNotas.value || '').trim() || null,
            }).then(function (d) {
                if (d.ok) {
                    location.reload();
                } else {
                    showError(decError, d.error || 'Error al declarar.');
                    btnSubmitDec.disabled    = false;
                    btnSubmitDec.textContent = 'Declarar corte';
                }
            }).catch(function () {
                showError(decError, 'Error de red. Intenta de nuevo.');
                btnSubmitDec.disabled    = false;
                btnSubmitDec.textContent = 'Declarar corte';
            });
        });
    }


    // ── MODAL DETALLE (admin) ────────────────────────────────

    if (!esAdmin) return;

    var modalDet         = document.getElementById('modal-detalle');
    var detView          = document.getElementById('det-view');
    var detEdit          = document.getElementById('det-edit');
    var detRechazar      = document.getElementById('det-rechazar');
    var detDl            = document.getElementById('det-dl');
    var detTitulo        = document.getElementById('det-titulo');
    var detActions       = document.getElementById('det-actions');
    var detActionsCerrar = document.getElementById('det-actions-cerrar');
    var detEmpId         = document.getElementById('det-emp-id');
    var detBruto         = document.getElementById('det-bruto');
    var detNotas         = document.getElementById('det-notas');
    var detError         = document.getElementById('det-edit-error');
    var detRecErr        = document.getElementById('det-rechazo-error');
    var detMotivo        = document.getElementById('det-motivo');

    var corteActual = null;

    var LABEL_TURNO  = { manana: 'Mañana', tarde: 'Tarde', noche: 'Noche' };
    var LABEL_ESTADO = { declarado: 'Declarado', editado: 'Editado', anulado: 'Anulado' };

    function renderDl(c) {
        var filas = [
            ['Turno',           LABEL_TURNO[c.turno]  || c.turno,       false],
            ['Fecha',           c.fecha,                                  true],
            ['Empleado',        c.emp_nombre || '—',                     false],
            ['Bruto sistema',   fmt(c.bruto_calculado),                   true],
            ['Bruto declarado', fmt(c.bruto_declarado),                   true],
            ['Estado',          LABEL_ESTADO[c.estado] || c.estado,      false],
        ];
        if (c.notas)          filas.push(['Notas',          c.notas,          false]);
        if (c.editado_por)    filas.push(['Editado por',    c.editado_por,    false]);
        if (c.estado === 'anulado' && c.confirmado_por) filas.push(['Anulado por', c.confirmado_por, false]);
        if (c.motivo_rechazo) filas.push(['Motivo anulación', c.motivo_rechazo, false]);

        detDl.innerHTML = filas.map(function (f) {
            return '<dt>' + f[0] + '</dt><dd class="' + (f[2] ? '' : 'dd--text') + '">' + f[1] + '</dd>';
        }).join('');
    }

    function mostrarView(c) {
        detView.hidden     = false;
        detEdit.hidden     = true;
        detRechazar.hidden = true;
        var editable = c.estado === 'declarado' || c.estado === 'editado';
        detActions.hidden       = !editable;
        detActionsCerrar.hidden = editable;
    }

    function abrirModalDetalle(c) {
        corteActual = c;
        detTitulo.textContent = 'Corte ' + (LABEL_TURNO[c.turno] || c.turno);
        renderDl(c);
        mostrarView(c);
        hideError(detError);
        hideError(detRecErr);
        detMotivo.value = '';
        modalDet.hidden = false;
    }

    document.querySelectorAll('.btn-ver-detalle').forEach(function (btn) {
        btn.addEventListener('click', function () {
            try { abrirModalDetalle(JSON.parse(btn.dataset.corte)); } catch (e) {}
        });
    });

    var detBtnCerrar = document.getElementById('det-btn-cerrar');
    if (detBtnCerrar) detBtnCerrar.addEventListener('click', function () { modalDet.hidden = true; });
    if (modalDet) modalDet.addEventListener('click', function (e) { if (e.target === modalDet) modalDet.hidden = true; });

    // Anular
    var btnRechazar = document.getElementById('det-btn-rechazar');
    if (btnRechazar) {
        btnRechazar.addEventListener('click', function () {
            detView.hidden     = true;
            detRechazar.hidden = false;
            detMotivo.focus();
        });
    }

    var btnCancelarRechazar = document.getElementById('det-btn-cancelar-rechazar');
    if (btnCancelarRechazar) btnCancelarRechazar.addEventListener('click', function () { mostrarView(corteActual); });

    var btnSubmitRechazar = document.getElementById('det-btn-submit-rechazar');
    if (btnSubmitRechazar) {
        btnSubmitRechazar.addEventListener('click', function () {
            if (!corteActual) return;
            hideError(detRecErr);
            btnSubmitRechazar.disabled = true;
            postJSON('/cortes/api/anular/' + corteActual.id, { motivo: detMotivo.value.trim() })
                .then(function (d) {
                    if (d.ok) { location.reload(); }
                    else { showError(detRecErr, d.error || 'Error'); btnSubmitRechazar.disabled = false; }
                })
                .catch(function () { showError(detRecErr, 'Error de red.'); btnSubmitRechazar.disabled = false; });
        });
    }

    // Editar — admin siempre ve todos los empleados (select ya renderizado en template)
    var btnEditar = document.getElementById('det-btn-editar');
    if (btnEditar) {
        btnEditar.addEventListener('click', function () {
            if (!corteActual) return;
            detView.hidden = true;
            detEdit.hidden = false;
            hideError(detError);
            if (corteActual.empleado_id) setOptionByValue(detEmpId, corteActual.empleado_id);
            detBruto.value = corteActual.bruto_declarado;
            detNotas.value = corteActual.notas || '';
        });
    }

    var btnCancelarEdit = document.getElementById('det-btn-cancelar-edit');
    if (btnCancelarEdit) btnCancelarEdit.addEventListener('click', function () { mostrarView(corteActual); });

    var btnSubmitEdit = document.getElementById('det-btn-submit-edit');
    if (btnSubmitEdit) {
        btnSubmitEdit.addEventListener('click', function () {
            if (!corteActual) return;
            hideError(detError);
            var empId = parseInt(detEmpId.value);
            var bruto = parseFloat(detBruto.value);
            if (!empId)                    { showError(detError, 'Selecciona un empleado.'); return; }
            if (isNaN(bruto) || bruto < 0) { showError(detError, 'Bruto inválido.'); return; }

            btnSubmitEdit.disabled    = true;
            btnSubmitEdit.textContent = 'Guardando...';

            postJSON('/cortes/api/editar/' + corteActual.id, {
                empleado_id:     empId,
                bruto_declarado: bruto,
                notas:           (detNotas.value || '').trim() || null,
            }).then(function (d) {
                if (d.ok) { location.reload(); }
                else {
                    showError(detError, d.error || 'Error.');
                    btnSubmitEdit.disabled    = false;
                    btnSubmitEdit.textContent = 'Guardar cambios';
                }
            }).catch(function () {
                showError(detError, 'Error de red.');
                btnSubmitEdit.disabled    = false;
                btnSubmitEdit.textContent = 'Guardar cambios';
            });
        });
    }

})();
