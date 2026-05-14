import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuditoriaService } from '../../core/services/auditoria.service';
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

    constructor(private auditoriaService: AuditoriaService) { }

    ngOnInit(): void {
        this.cargarAuditoria();
    }

    cargarAuditoria(): void {
        this.auditoriaService.listar().subscribe({
            next: (data: any) => this.auditoria = data,
            error: (err: any) => console.error(err)
        });
    }

    get auditoriaFiltrada(): any[] {
        return this.auditoria.filter((a: any) => {
            const matchUsuario = this.filtroUsuario
                ? a.usuario?.toLowerCase().includes(this.filtroUsuario.toLowerCase())
                : true;

            const fecha = new Date(a.fecha);

            const matchInicio = this.fechaInicio
                ? fecha >= new Date(this.fechaInicio)
                : true;

            const matchFin = this.fechaFin
                ? fecha <= new Date(this.fechaFin)
                : true;

            return matchUsuario && matchInicio && matchFin;
        });
    }

    exportarExcel(): void {
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
        const doc = new jsPDF();

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
            ])
        });

        doc.save('auditoria.pdf');
    }

}