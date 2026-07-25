// Document and batch types for the intraday trade hub

export interface Document {
  id: string;
  title: string;
  description: string;
  slug: string;
  batchId: string;
  releaseDate: Date;
  publishedDate: string;
  type: 'research' | 'analysis' | 'update' | 'report';
  documentType: 'research' | 'analysis' | 'update' | 'report';
  tags: string[];
  author: string;
  fileUrl?: string;
  pageCount?: number;
  isPublished: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface Batch {
  id: string;
  name: string;
  title?: string;
  description: string;
  releaseDate: Date;
  documentIds: string[];
  status: 'draft' | 'scheduled' | 'released' | 'archived';
  kimiPrompt?: string;
  totalDocuments: number;
  documentCount?: number;
  isPublished: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface Upload {
  id: string;
  fileName: string;
  fileSize: number;
  uploadedAt: Date;
  uploadedBy: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  batchId?: string;
  documentId?: string;
  errorMessage?: string;
}

export interface AuditLog {
  id: string;
  action: string;
  entityType: 'document' | 'batch' | 'upload' | 'settings';
  entityId: string;
  userId: string;
  timestamp: Date;
  details: Record<string, any>;
}

export interface DashboardStats {
  totalDocuments: number;
  totalBatches: number;
  totalUploads: number;
  publishedDocuments: number;
  pendingUploads: number;
  recentActivity: AuditLog[];
}

export interface FilterOptions {
  searchQuery?: string;
  documentType?: string;
  tags?: string[];
  dateFrom?: Date;
  dateTo?: Date;
  author?: string;
  status?: string;
  sortBy?: 'date' | 'title' | 'relevance';
  sortOrder?: 'asc' | 'desc';
}
