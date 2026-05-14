import { Injectable } from '@angular/core';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class ReportesService {
  constructor(private api: ApiService) {}

  resumen() {
    return this.api.get('reportes/resumen');
  }
}