import { Component, OnInit, AfterViewInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { RouterModule } from '@angular/router';
import { forkJoin, catchError, finalize, of, timeout } from 'rxjs';
import Swal from 'sweetalert2';
import Chart from 'chart.js/auto';

@Component({
  selector: 'app-reportes',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './reportes.html',
  styleUrl: './reportes.scss'
})
export class Reportes implements OnInit, AfterViewInit {

  resumen: any = {
    usuarios: 0,
    documentos: 0
  };

  estadoData: any[] = [];

  chartResumen: any;
  chartEstado: any;

  cargando = false;
  error = '';
  vistaLista = false;

  private api = 'http://localhost:5000/api';

  constructor(
    private http: HttpClient,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.cargarReportes();
  }

  ngAfterViewInit(): void {
    this.vistaLista = true;
    this.crearGraficos();
  }

  cargarReportes(): void {
    if (this.cargando) return;

    this.cargando = true;
    this.error = '';

    forkJoin({
      resumen: this.http.get<any>(`${this.api}/reportes/resumen`),
      estados: this.http.get<any[]>(`${this.api}/reportes/estado-documentos`)
    }).pipe(
      timeout(4000),

      catchError((err: any) => {
        if (err.status === 401) {
          this.error = 'Sesión expirada. Inicie sesión nuevamente.';
        } else if (err.status === 403) {
          this.error = 'No tiene permisos para ver reportes.';
        } else if (err.name === 'TimeoutError') {
          this.error = 'El servidor tardó demasiado.';
        } else {
          this.error = err.error?.mensaje || 'Error al cargar reportes.';
        }

        Swal.fire('Error', this.error, 'error');

        return of({
          resumen: { usuarios: 0, documentos: 0 },
          estados: []
        });
      }),

      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((res: any) => {
      this.resumen = res.resumen || { usuarios: 0, documentos: 0 };
      this.estadoData = res.estados || [];

      this.cdr.detectChanges();
      this.crearGraficos();
    });
  }

  validarResumen(): boolean {
    return (
      this.resumen &&
      Number(this.resumen.usuarios) >= 0 &&
      Number(this.resumen.documentos) >= 0
    );
  }

  validarEstados(): boolean {
    return Array.isArray(this.estadoData);
  }

  crearGraficos(): void {
    if (!this.vistaLista) return;

    this.crearGraficoResumen();
    this.crearGraficoEstado();
  }

  crearGraficoResumen(): void {
    if (!this.validarResumen()) return;

    const ctx = document.getElementById('grafico') as HTMLCanvasElement;
    if (!ctx) return;

    if (this.chartResumen) {
      this.chartResumen.destroy();
    }

    this.chartResumen = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['Usuarios', 'Documentos'],
        datasets: [{
          label: 'Sistema INAMHI',
          data: [
            Number(this.resumen.usuarios) || 0,
            Number(this.resumen.documentos) || 0
          ],
          backgroundColor: ['#3b82f6', '#10b981'],
          borderRadius: 10
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: {
          duration: 500
        },
        plugins: {
          legend: {
            display: false
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              precision: 0
            }
          }
        }
      }
    });
  }

  crearGraficoEstado(): void {
    if (!this.validarEstados()) return;

    const ctx = document.getElementById('graficoEstado') as HTMLCanvasElement;
    if (!ctx) return;

    if (this.chartEstado) {
      this.chartEstado.destroy();
    }

    const labels = this.estadoData.map(e => e.estado || 'SIN ESTADO');
    const valores = this.estadoData.map(e => Number(e.cantidad) || 0);

    this.chartEstado = new Chart(ctx, {
      type: 'pie',
      data: {
        labels,
        datasets: [{
          data: valores,
          backgroundColor: [
            '#f59e0b',
            '#10b981',
            '#ef4444',
            '#3b82f6',
            '#8b5cf6'
          ]
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: {
          duration: 500
        }
      }
    });
  }

  recargar(): void {
    this.cargarReportes();
  }
}