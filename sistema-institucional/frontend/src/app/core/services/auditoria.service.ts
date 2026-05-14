import { Injectable } from '@angular/core';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class AuditoriaService {
  constructor(private api: ApiService) {}

  listar() {
    return this.api.get('auditoria');
  }
}