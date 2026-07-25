import {
  Document,
  Batch,
  Upload,
  AuditLog,
  DashboardStats,
  FilterOptions,
} from './types';
import {
  mockDocuments,
  mockBatches,
  mockUploads,
  mockAuditLogs,
  mockDashboardStats,
} from './mock-data';

// These services abstract the data layer, allowing easy migration to real APIs

export const documentService = {
  async getAll(filters?: FilterOptions): Promise<Document[]> {
    let results = [...mockDocuments];

    if (filters?.searchQuery) {
      const query = filters.searchQuery.toLowerCase();
      results = results.filter(
        (doc) =>
          doc.title.toLowerCase().includes(query) ||
          doc.description.toLowerCase().includes(query)
      );
    }

    if (filters?.documentType) {
      results = results.filter((doc) => doc.documentType === filters.documentType);
    }

    if (filters?.tags && filters.tags.length > 0) {
      results = results.filter((doc) =>
        filters.tags?.some((tag) => doc.tags.includes(tag))
      );
    }

    if (filters?.author) {
      results = results.filter((doc) => doc.author === filters.author);
    }

    if (filters?.sortBy === 'date') {
      results.sort((a, b) =>
        filters.sortOrder === 'asc'
          ? a.releaseDate.getTime() - b.releaseDate.getTime()
          : b.releaseDate.getTime() - a.releaseDate.getTime()
      );
    } else if (filters?.sortBy === 'title') {
      results.sort((a, b) =>
        filters.sortOrder === 'asc'
          ? a.title.localeCompare(b.title)
          : b.title.localeCompare(a.title)
      );
    }

    return results.filter((doc) => doc.isPublished);
  },

  async getById(id: string): Promise<Document | null> {
    return mockDocuments.find((doc) => doc.id === id) || null;
  },

  async getBySlug(slug: string): Promise<Document | null> {
    return mockDocuments.find((doc) => doc.slug === slug) || null;
  },

  getDocumentBySlug(slug: string): Document | undefined {
    return mockDocuments.find((doc) => doc.slug === slug);
  },

  async getByBatchId(batchId: string): Promise<Document[]> {
    return mockDocuments.filter((doc) => doc.batchId === batchId);
  },

  async create(data: Omit<Document, 'id' | 'createdAt' | 'updatedAt'>): Promise<Document> {
    const doc: Document = {
      ...data,
      id: `doc-${Date.now()}`,
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    mockDocuments.push(doc);
    return doc;
  },

  async update(id: string, data: Partial<Document>): Promise<Document | null> {
    const doc = mockDocuments.find((d) => d.id === id);
    if (!doc) return null;
    Object.assign(doc, data, { updatedAt: new Date() });
    return doc;
  },

  async delete(id: string): Promise<boolean> {
    const index = mockDocuments.findIndex((d) => d.id === id);
    if (index === -1) return false;
    mockDocuments.splice(index, 1);
    return true;
  },
};

export const batchService = {
  async getAll(): Promise<Batch[]> {
    return [...mockBatches];
  },

  async getPublished(): Promise<Batch[]> {
    return mockBatches.filter((batch) => batch.isPublished);
  },

  async getById(id: string): Promise<Batch | null> {
    return mockBatches.find((batch) => batch.id === id) || null;
  },

  async create(data: Omit<Batch, 'id' | 'createdAt' | 'updatedAt'>): Promise<Batch> {
    const batch: Batch = {
      ...data,
      id: `batch-${Date.now()}`,
      createdAt: new Date(),
      updatedAt: new Date(),
    };
    mockBatches.push(batch);
    return batch;
  },

  async update(id: string, data: Partial<Batch>): Promise<Batch | null> {
    const batch = mockBatches.find((b) => b.id === id);
    if (!batch) return null;
    Object.assign(batch, data, { updatedAt: new Date() });
    return batch;
  },

  async delete(id: string): Promise<boolean> {
    const index = mockBatches.findIndex((b) => b.id === id);
    if (index === -1) return false;
    mockBatches.splice(index, 1);
    return true;
  },
};

export const uploadService = {
  async getAll(): Promise<Upload[]> {
    return [...mockUploads];
  },

  async getById(id: string): Promise<Upload | null> {
    return mockUploads.find((upload) => upload.id === id) || null;
  },

  async getByBatchId(batchId: string): Promise<Upload[]> {
    return mockUploads.filter((upload) => upload.batchId === batchId);
  },

  async create(data: Omit<Upload, 'id'>): Promise<Upload> {
    const upload: Upload = {
      ...data,
      id: `upload-${Date.now()}`,
    };
    mockUploads.push(upload);
    return upload;
  },

  async update(id: string, data: Partial<Upload>): Promise<Upload | null> {
    const upload = mockUploads.find((u) => u.id === id);
    if (!upload) return null;
    Object.assign(upload, data);
    return upload;
  },

  async delete(id: string): Promise<boolean> {
    const index = mockUploads.findIndex((u) => u.id === id);
    if (index === -1) return false;
    mockUploads.splice(index, 1);
    return true;
  },
};

export const auditService = {
  async getAll(): Promise<AuditLog[]> {
    return mockAuditLogs;
  },

  async log(
    action: string,
    entityType: AuditLog['entityType'],
    entityId: string,
    userId: string,
    details?: Record<string, any>
  ): Promise<AuditLog> {
    const log: AuditLog = {
      id: `log-${Date.now()}`,
      action,
      entityType,
      entityId,
      userId,
      timestamp: new Date(),
      details: details || {},
    };
    mockAuditLogs.push(log);
    return log;
  },
};

export const dashboardService = {
  async getStats(): Promise<DashboardStats> {
    return {
      ...mockDashboardStats,
      totalDocuments: mockDocuments.length,
      totalBatches: mockBatches.length,
      totalUploads: mockUploads.length,
      publishedDocuments: mockDocuments.filter((d) => d.isPublished).length,
      pendingUploads: mockUploads.filter((u) => u.status === 'pending').length,
      recentActivity: mockAuditLogs.slice(0, 5),
    };
  },
};
