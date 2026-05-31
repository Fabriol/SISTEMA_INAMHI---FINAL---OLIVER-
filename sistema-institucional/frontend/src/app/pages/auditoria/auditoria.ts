import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuditoriaService } from '../../core/services/auditoria.service';
import { catchError, finalize, of, timeout } from 'rxjs';
import Swal from 'sweetalert2';
import * as XLSX from 'xlsx';
import { saveAs } from 'file-saver';
import jsPDF from 'jspdf';
import autoTable from 'jspdf-autotable';

@Component({
  selector: 'app-auditoria',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './auditoria.html',
  styleUrl: './auditoria.scss'
})
export class Auditoria implements OnInit {

  auditoria: any[] = [];

  filtroUsuario = '';
  fechaInicio = '';
  fechaFin = '';

  cargando = false;
  error = '';
  errorFechas = '';

  readonly hoy: string = new Date().toISOString().split('T')[0];

  constructor(
    private auditoriaService: AuditoriaService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.cargarAuditoria();
  }

  cargarAuditoria(): void {
    if (this.cargando) return;

    this.cargando = true;
    this.error = '';

    this.auditoriaService.listar().pipe(
      timeout(4000),

      catchError((err: any) => {
        if (err.status === 401) {
          this.error = 'Sesión expirada. Inicie sesión nuevamente.';
        } else if (err.status === 403) {
          this.error = 'No tiene permisos para ver auditoría.';
        } else if (err.name === 'TimeoutError') {
          this.error = 'El servidor tardó demasiado.';
        } else {
          this.error = err.error?.mensaje || 'Error al cargar auditoría.';
        }

        Swal.fire('Error', this.error, 'error');
        return of([]);
      }),

      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((data: any) => {
      this.auditoria = data || [];
      this.cdr.detectChanges();
    });
  }

  validarFechas(): boolean {
    this.errorFechas = '';

    const hoyDate = new Date();
    hoyDate.setHours(23, 59, 59, 999);

    if (this.fechaInicio) {
      const inicio = new Date(this.fechaInicio);
      if (isNaN(inicio.getTime())) {
        this.errorFechas = 'Fecha inicio inválida.';
        return false;
      }
      if (inicio > hoyDate) {
        this.errorFechas = 'La fecha inicio no puede ser futura.';
        return false;
      }
    }

    if (this.fechaFin) {
      const fin = new Date(this.fechaFin);
      if (isNaN(fin.getTime())) {
        this.errorFechas = 'Fecha fin inválida.';
        return false;
      }
      if (fin > hoyDate) {
        this.errorFechas = 'La fecha fin no puede ser futura.';
        return false;
      }
    }

    if (this.fechaInicio && this.fechaFin) {
      const inicio = new Date(this.fechaInicio);
      const fin = new Date(this.fechaFin);
      if (inicio > fin) {
        this.errorFechas = 'La fecha inicio no puede ser posterior a la fecha fin.';
        return false;
      }
    }

    return true;
  }

  onFechaChange(): void {
    this.validarFechas();
  }

  filtroUsuarioValido(): boolean {
    return this.filtroUsuario.length <= 60;
  }

  limpiarFiltros(): void {
    this.filtroUsuario = '';
    this.fechaInicio = '';
    this.fechaFin = '';
    this.errorFechas = '';
  }

  get auditoriaFiltrada(): any[] {
    if (!this.validarFechas()) return [];
    if (!this.filtroUsuarioValido()) return [];

    const filtroLimpio = this.filtroUsuario.trim().toLowerCase().slice(0, 60);

    return this.auditoria.filter((a: any) => {
      const usuario = (a.usuario || '').toLowerCase();
      const matchUsuario = filtroLimpio ? usuario.includes(filtroLimpio) : true;

      const fecha = new Date(a.fecha);
      const matchInicio = this.fechaInicio ? fecha >= new Date(this.fechaInicio) : true;
      const matchFin = this.fechaFin ? fecha <= new Date(this.fechaFin + 'T23:59:59') : true;

      return matchUsuario && matchInicio && matchFin;
    });
  }

  exportarExcel(): void {
    if (this.auditoriaFiltrada.length === 0) {
      Swal.fire('Sin datos', 'No hay registros para exportar.', 'warning');
      return;
    }

    const ahora    = new Date();
    const fechaStr = ahora.toLocaleDateString('es-EC', { day:'2-digit', month:'2-digit', year:'numeric' });
    const horaStr  = ahora.toLocaleTimeString('es-EC', { hour:'2-digit', minute:'2-digit' });
    const nombre   = `INAMHI_Auditoria_${fechaStr.replace(/\//g, '-')}.xls`;

    const filtros: string[] = [];
    if (this.filtroUsuario.trim()) filtros.push(`Usuario: "${this.filtroUsuario.trim()}"`);
    if (this.fechaInicio)          filtros.push(`Desde: ${this.fechaInicio}`);
    if (this.fechaFin)             filtros.push(`Hasta: ${this.fechaFin}`);
    const filtrosTexto = filtros.length ? filtros.join(' | ') : 'Sin filtros (todos los registros)';

    // ── Resumen por módulo ────────────────────────────────────────────────
    const porModulo: Record<string, number> = {};
    this.auditoriaFiltrada.forEach((a: any) => {
      const m = a.modulo || 'Sin módulo';
      porModulo[m] = (porModulo[m] || 0) + 1;
    });

    // ── Helper para escapar HTML ──────────────────────────────────────────
    const esc = (v: any): string => String(v ?? '—')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

    const fmtFecha = (f: any): string => f
      ? new Date(f).toLocaleString('es-EC', { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit' })
      : '—';

    // ── Filas de datos ────────────────────────────────────────────────────
    const filasDatos = this.auditoriaFiltrada.map((a: any, i: number) => {
      const bg  = i % 2 === 0 ? '#FFFFFF' : '#EFF6FF';
      const bgF = i % 2 === 0 ? '#F8FAFC' : '#DBEAFE';
      return `
        <tr>
          <td style="background:${bgF};text-align:center;font-weight:700;color:#1D4ED8;border:1px solid #E2E8F0;">${i + 1}</td>
          <td style="background:${bg};border:1px solid #E2E8F0;">${esc(a.nombre_completo || a.usuario)}</td>
          <td style="background:${bg};border:1px solid #E2E8F0;color:#64748b;">${esc(a.usuario)}</td>
          <td style="background:${bg};border:1px solid #E2E8F0;">${esc(a.rol)}</td>
          <td style="background:${bg};border:1px solid #E2E8F0;text-align:center;">${esc(a.modulo)}</td>
          <td style="background:${bg};border:1px solid #E2E8F0;color:#0284C7;">${esc(a.accion)}</td>
          <td style="background:${bg};border:1px solid #E2E8F0;">${esc(a.detalle)}</td>
          <td style="background:${bgF};border:1px solid #E2E8F0;text-align:center;color:#475569;font-size:9pt;">${esc(fmtFecha(a.fecha))}</td>
        </tr>`;
    }).join('');

    // ── Filas de resumen ──────────────────────────────────────────────────
    const filasResumen = Object.entries(porModulo)
      .sort((a, b) => b[1] - a[1])
      .map(([mod, cnt], i) => {
        const bg = i % 2 === 0 ? '#FFFFFF' : '#EFF6FF';
        return `<tr>
          <td style="background:${bg};border:1px solid #E2E8F0;padding:5px 8px;">${esc(mod)}</td>
          <td style="background:${bg};border:1px solid #E2E8F0;text-align:center;font-weight:700;">${cnt}</td>
        </tr>`;
      }).join('');

    // ── HTML completo del libro Excel ─────────────────────────────────────
    const html = `
<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:x="urn:schemas-microsoft-com:office:excel"
      xmlns="http://www.w3.org/TR/REC-html40">
<head>
  <meta charset="UTF-8">
  <!--[if gte mso 9]><xml>
    <x:ExcelWorkbook><x:ExcelWorksheets>
      <x:ExcelWorksheet><x:Name>Auditoría</x:Name>
        <x:WorksheetOptions><x:Selected/><x:FreezePanes/><x:FrozenNoSplit/>
          <x:SplitHorizontal>6</x:SplitHorizontal><x:TopRowBottomPane>6</x:TopRowBottomPane>
        </x:WorksheetOptions>
      </x:ExcelWorksheet>
      <x:ExcelWorksheet><x:Name>Resumen</x:Name></x:ExcelWorksheet>
    </x:ExcelWorksheets></x:ExcelWorkbook>
  </xml><![endif]-->
  <style>
    body  { font-family: Calibri, Arial; font-size: 10pt; }
    table { border-collapse: collapse; width: 100%; }
    td    { padding: 5px 8px; vertical-align: top; }
    .t1   { background:#1E3A8A; color:#FFFFFF; font-size:14pt; font-weight:bold; padding:12px 10px; }
    .t2   { background:#1E3A8A; color:#BFDBFE; font-size:10pt; padding:6px 10px; }
    .meta { background:#EEF2FF; color:#374151; font-size:9pt; padding:5px 10px; }
    .metav{ background:#EEF2FF; color:#1E3A8A; font-weight:bold; font-size:9pt; padding:5px 8px; }
    .ch   { background:#1D4ED8; color:#FFFFFF; font-weight:bold; text-align:center; border:1px solid #93C5FD; padding:7px 6px; font-size:9pt; }
    .tot  { background:#1E3A8A; color:#FFFFFF; font-weight:bold; border:1px solid #93C5FD; padding:6px 8px; }
  </style>
</head>
<body>

<!-- HOJA 1: AUDITORÍA -->
<table>
  <tr><td colspan="8" class="t1">INAMHI — Instituto Nacional de Meteorología e Hidrología</td></tr>
  <tr><td colspan="8" class="t2">Sistema Institucional Inteligente — Módulo de Auditoría</td></tr>
  <tr><td colspan="8" style="background:#1E3A8A;height:4px;"></td></tr>
  <tr>
    <td class="meta">Generado:</td><td class="metav">${fechaStr} ${horaStr}</td>
    <td class="meta">Registros:</td><td class="metav">${this.auditoriaFiltrada.length}</td>
    <td colspan="2" class="meta">Filtros:</td><td colspan="2" class="metav">${esc(filtrosTexto)}</td>
  </tr>
  <tr><td colspan="8" style="background:#1E3A8A;height:4px;"></td></tr>
  <tr>
    <td class="ch" style="width:30px;">N°</td>
    <td class="ch">Nombres y Apellidos</td>
    <td class="ch">Usuario</td>
    <td class="ch">Rol</td>
    <td class="ch">Módulo</td>
    <td class="ch">Acción</td>
    <td class="ch" style="width:300px;">Detalle</td>
    <td class="ch">Fecha / Hora</td>
  </tr>
  ${filasDatos}
  <tr>
    <td colspan="6" class="tot" style="text-align:right;">Total de registros:</td>
    <td colspan="2" class="tot" style="text-align:center;">${this.auditoriaFiltrada.length}</td>
  </tr>
</table>

<br><br>

<!-- HOJA 2: RESUMEN (misma hoja en xls, separado visualmente) -->
<table style="width:400px;">
  <tr><td colspan="2" class="t1">Resumen por Módulo</td></tr>
  <tr><td class="ch">Módulo</td><td class="ch">Acciones registradas</td></tr>
  ${filasResumen}
  <tr>
    <td class="tot">TOTAL</td>
    <td class="tot" style="text-align:center;">${this.auditoriaFiltrada.length}</td>
  </tr>
</table>

</body></html>`;

    const blob = new Blob(['﻿' + html], {
      type: 'application/vnd.ms-excel;charset=utf-8'
    });
    saveAs(blob, nombre);
  }

  exportarPDF(): void {
    if (this.auditoriaFiltrada.length === 0) {
      Swal.fire('Sin datos', 'No hay registros para exportar.', 'warning');
      return;
    }

    const doc = new jsPDF('landscape');

    doc.setFontSize(16);
    doc.text('Reporte de Auditoría del Sistema', 14, 15);

    autoTable(doc, {
      startY: 25,
      head: [['ID', 'Usuario', 'Rol', 'Módulo', 'Acción', 'Detalle', 'Fecha']],
      body: this.auditoriaFiltrada.map((a: any) => [
        a.id,
        a.usuario,
        a.rol,
        a.modulo,
        a.accion,
        a.detalle,
        a.fecha
      ]),
      styles: {
        fontSize: 8
      },
      headStyles: {
        fillColor: [15, 23, 42]
      }
    });

    doc.save('auditoria.pdf');
  }
}