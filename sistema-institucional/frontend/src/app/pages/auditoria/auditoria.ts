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
    if (this.fechaInicio && this.fechaFin) {
      const inicio = new Date(this.fechaInicio);
      const fin = new Date(this.fechaFin);

      if (inicio > fin) {
        Swal.fire('Fechas inválidas', 'La fecha inicio no puede ser mayor que la fecha fin.', 'warning');
        return false;
      }
    }

    return true;
  }

  limpiarFiltros(): void {
    this.filtroUsuario = '';
    this.fechaInicio = '';
    this.fechaFin = '';
  }

  get auditoriaFiltrada(): any[] {
    if (!this.validarFechas()) return [];

    return this.auditoria.filter((a: any) => {
      const usuario = (a.usuario || '').toLowerCase();
      const filtro = this.filtroUsuario.toLowerCase().trim();

      const matchUsuario = filtro ? usuario.includes(filtro) : true;

      const fecha = new Date(a.fecha);

      const matchInicio = this.fechaInicio
        ? fecha >= new Date(this.fechaInicio)
        : true;

      const matchFin = this.fechaFin
        ? fecha <= new Date(this.fechaFin + 'T23:59:59')
        : true;

      return matchUsuario && matchInicio && matchFin;
    });
  }

  exportarExcel(): void {
    if (this.auditoriaFiltrada.length === 0) {
      Swal.fire('Sin datos', 'No hay registros para exportar.', 'warning');
      return;
    }

    const data = this.auditoriaFiltrada.map((a: any) => ({
      ID: a.id,
      Usuario: a.usuario,
      Rol: a.rol,
      Modulo: a.modulo,
      Accion: a.accion,
      Detalle: a.detalle,
      Fecha: a.fecha
    }));

    const worksheet = XLSX.utils.json_to_sheet(data);
    const workbook = XLSX.utils.book_new();

    XLSX.utils.book_append_sheet(workbook, worksheet, 'Auditoria');

    const excelBuffer = XLSX.write(workbook, {
      bookType: 'xlsx',
      type: 'array'
    });

    const blob = new Blob([excelBuffer], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    });

    saveAs(blob, 'auditoria.xlsx');
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