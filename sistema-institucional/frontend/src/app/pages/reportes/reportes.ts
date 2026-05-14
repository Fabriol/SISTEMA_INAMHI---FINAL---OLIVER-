import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { RouterModule } from '@angular/router';
import Chart from 'chart.js/auto';

@Component({
  selector: 'app-reportes',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './reportes.html',
  styleUrl: './reportes.scss'
})
export class Reportes implements OnInit {

  resumen: any = {
    usuarios: 0,
    documentos: 0
  };

  estadoData: any[] = [];

  chartResumen: any;
  chartEstado: any;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.cargarResumen();
    this.cargarEstadoDocumentos();
  }

  cargarResumen(): void {
    this.http.get<any>('http://localhost:5000/api/reportes/resumen')
      .subscribe({
        next: data => {
          this.resumen = data;
          this.crearGraficoResumen();
        },
        error: err => console.error('Error resumen:', err)
      });
  }

  cargarEstadoDocumentos(): void {
    this.http.get<any[]>('http://localhost:5000/api/reportes/estado-documentos')
      .subscribe({
        next: data => {
          this.estadoData = data;
          this.crearGraficoEstado();
        },
        error: err => console.error('Error estados:', err)
      });
  }

  crearGraficoResumen(): void {
    if (this.chartResumen) {
      this.chartResumen.destroy();
    }

    const ctx: any = document.getElementById('grafico');
    if (!ctx) return;

    this.chartResumen = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['Usuarios', 'Documentos'],
        datasets: [{
          label: 'Sistema INAMHI',
          data: [this.resumen.usuarios, this.resumen.documentos],
          backgroundColor: ['#3b82f6', '#10b981'],
          borderRadius: 8
        }]
      },
      options: {
        responsive: true
      }
    });
  }

  crearGraficoEstado(): void {
    if (this.chartEstado) {
      this.chartEstado.destroy();
    }

    const ctx: any = document.getElementById('graficoEstado');
    if (!ctx) return;

    this.chartEstado = new Chart(ctx, {
      type: 'pie',
      data: {
        labels: this.estadoData.map(e => e.estado),
        datasets: [{
          data: this.estadoData.map(e => e.cantidad),
          backgroundColor: [
            '#f59e0b',
            '#10b981',
            '#ef4444',
            '#3b82f6'
          ]
        }]
      },
      options: {
        responsive: true
      }
    });
  }
}