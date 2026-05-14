import { Component, OnInit, Inject, PLATFORM_ID } from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { ReportesService } from '../../core/services/reportes.service';
import { AfterViewInit } from '@angular/core';
import Chart from 'chart.js/auto';


@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss'
})
export class Dashboard implements OnInit, AfterViewInit {
  usuario: any = {};

  resumen: any = {
    usuarios: 0,
    documentos: 0
  };

  menu: any[] = [];

  constructor(
    private router: Router,
    private reportesService: ReportesService,
    @Inject(PLATFORM_ID) private platformId: Object
  ) { }

  ngOnInit(): void {
    if (isPlatformBrowser(this.platformId)) {
      this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');
    }

    this.cargarResumen();
    this.cargarMenu();
  }

  chart: any;

  ngAfterViewInit(): void {
    setTimeout(() => {
      this.crearGrafico();
    }, 500);
  }

  cargarResumen(): void {
    this.reportesService.resumen().subscribe({
      next: (data: any) => {
        this.resumen = data;
        this.crearGrafico(); // 👈 AQUÍ
      },
      error: () => {
        console.log('Error cargando resumen');
      }
    });
  }

  cargarMenu(): void {
    const rol = this.usuario?.rol;

    if (rol === 'Administrador') {
      this.menu = [
        { nombre: 'Dashboard', ruta: '/dashboard' },
        { nombre: 'Usuarios', ruta: '/usuarios' },
        { nombre: 'Documentos', ruta: '/documentos' },
        { nombre: 'Reportes', ruta: '/reportes' },
        { nombre: 'Auditoría', ruta: '/auditoria' }
      ];
    } else if (rol === 'Talento Humano - Recepcion Documentos') {
      this.menu = [
        { nombre: 'Dashboard', ruta: '/dashboard' },
        { nombre: 'Documentos', ruta: '/documentos' },
        { nombre: 'Reportes', ruta: '/reportes' }
      ];
    } else if (rol === 'Ex Funcionario') {
      this.menu = [
        { nombre: 'Dashboard', ruta: '/dashboard' },
        { nombre: 'Mis Documentos', ruta: '/documentos' }
      ];
    } else if (rol === 'Administrativa' || rol === 'Financiera' || rol === 'TICs' || rol === 'Seguridad') {
      this.menu = [
        { nombre: 'Dashboard', ruta: '/dashboard' },
        { nombre: 'Documentos', ruta: '/documentos' }
      ];
    } else {
      this.menu = [
        { nombre: 'Dashboard', ruta: '/dashboard' }
      ];
    }
  }

  logout(): void {
    if (isPlatformBrowser(this.platformId)) {
      localStorage.clear();
    }

    this.router.navigate(['/login']);
  }
  crearGrafico(): void {
    const ctx = document.getElementById('grafico') as any;

    if (!ctx) return;

    this.chart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: ['Usuarios', 'Documentos'],
        datasets: [
          {
            label: 'Cantidad',
            data: [
              this.resumen.usuarios,
              this.resumen.documentos
            ],
            backgroundColor: [
              '#2563eb',
              '#16a34a'
            ]
          }
        ]
      },
      options: {
        responsive: true,
        plugins: {
          legend: {
            display: false
          }
        }
      }
    });
  }
}