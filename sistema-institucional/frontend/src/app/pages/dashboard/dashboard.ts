import {
  Component,
  OnInit,
  AfterViewInit,
  ChangeDetectorRef,
  PLATFORM_ID,
  inject
} from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { ReportesService } from '../../core/services/reportes.service';
import { catchError, finalize, of, timeout } from 'rxjs';
import Swal from 'sweetalert2';
import Chart from 'chart.js/auto';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss'
})
export class Dashboard implements OnInit, AfterViewInit {

  private platformId = inject(PLATFORM_ID);

  usuario: any = {};
  cargando = false;
  error = '';

  resumen: any = {
    usuarios: 0,
    documentos: 0
  };

  menu: any[] = [];
  chart: any;
  private vistaLista = false;

  constructor(
    private router: Router,
    private reportesService: ReportesService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    if (isPlatformBrowser(this.platformId)) {
      this.usuario = JSON.parse(localStorage.getItem('usuario') || '{}');
    }

    this.cargarMenu();
    this.cargarResumen();
  }

  ngAfterViewInit(): void {
    this.vistaLista = true;
    this.crearGrafico();
  }

  esAdmin(): boolean {
    return this.usuario?.rol === 'Administrador';
  }

  private normalizarRol(rol: string): string {
    return (rol || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').trim();
  }

  esTalentoHumano(): boolean {
    const r = this.normalizarRol(this.usuario?.rol);
    return r.includes('talento humano') && r.includes('recep');
  }

  cargarMenu(): void {
    const admin = this.esAdmin();
    const th    = this.esTalentoHumano();

    // Items siempre visibles
    const base = [
      { nombre: 'Dashboard',    ruta: '/dashboard' },
      { nombre: 'Documentos',   ruta: '/documentos' },
      { nombre: 'Formularios',  ruta: '/formularios' },
    ];

    // Items adicionales según rol — solo aparecen si tienen acceso
    if (admin) {
      base.push(
        { nombre: 'Usuarios',   ruta: '/usuarios' },
        { nombre: 'Reportes',   ruta: '/reportes' },
        { nombre: 'Auditoría',  ruta: '/auditoria' },
      );
    } else if (th) {
      base.push({ nombre: 'Reportes', ruta: '/reportes' });
    }

    this.menu = base.map(i => ({ ...i, bloqueado: false }));
  }

  navegar(item: any): void {
    if (item.bloqueado) {
      Swal.fire({
        icon: 'warning',
        title: 'Acceso bloqueado',
        text: 'Solo el Administrador puede ingresar a esta sección.',
        timer: 1800,
        showConfirmButton: false
      });
      return;
    }

    this.router.navigate([item.ruta]);
  }

  cargarResumen(): void {
    this.cargando = true;
    this.error = '';

    this.reportesService.resumen().pipe(
      timeout(3000),
      catchError((err: any) => {
        if (err.status === 401) {
          this.error = 'Sesión expirada';
          this.logout();
        } else {
          this.error = err.error?.mensaje || 'Error al cargar resumen';
        }

        return of({ usuarios: 0, documentos: 0 });
      }),
      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((data: any) => {
      this.resumen = data || { usuarios: 0, documentos: 0 };
      this.cdr.detectChanges();
      this.crearGrafico();
    });
  }

  crearGrafico(): void {
    if (!isPlatformBrowser(this.platformId)) return;
    if (!this.vistaLista) return;

    const canvas = document.getElementById('grafico') as HTMLCanvasElement;
    if (!canvas) return;

    if (this.chart) {
      this.chart.destroy();
    }

    this.chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: ['Usuarios', 'Documentos'],
        datasets: [{
          label: 'Cantidad',
          data: [
            this.resumen?.usuarios || 0,
            this.resumen?.documentos || 0
          ],
          backgroundColor: ['#2563eb', '#16a34a'],
          borderRadius: 10
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 500 },
        plugins: { legend: { display: false } },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { precision: 0 }
          }
        }
      }
    });
  }

  recargar(): void {
    this.cargarResumen();
  }

  logout(): void {
    if (isPlatformBrowser(this.platformId)) {
      localStorage.clear();
    }

    this.router.navigate(['/login']);
  }
}