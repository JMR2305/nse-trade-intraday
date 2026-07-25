'use client';

import { useState, useEffect } from 'react';
import { AppHeader } from '@/components/app-header';
import { DocumentCard } from '@/components/document-card';
import { FilterBar } from '@/components/filter-bar';
import { Document, FilterOptions } from '@/lib/types';
import { documentService } from '@/lib/services';
import { Plus } from 'lucide-react';

export default function HomePage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [filters, setFilters] = useState<FilterOptions>({
    sortBy: 'date',
    sortOrder: 'desc',
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadDocuments = async () => {
      setLoading(true);
      const docs = await documentService.getAll(filters);
      setDocuments(docs);
      setLoading(false);
    };
    loadDocuments();
  }, [filters]);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight mb-2">
            Research Documents
          </h1>
          <p className="text-muted-foreground">
            Browse and download the latest intraday trading research and analysis
          </p>
        </div>

        <div className="mb-8">
          <FilterBar
            filters={filters}
            onFiltersChange={setFilters}
            showDocumentType={true}
            showSortBy={true}
          />
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="text-muted-foreground">Loading documents...</div>
          </div>
        ) : documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <Plus className="h-12 w-12 text-muted-foreground mb-4 opacity-50" />
            <p className="text-muted-foreground">No documents found</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {documents.map((doc) => (
              <DocumentCard
                key={doc.id}
                document={doc}
                onClick={() => {
                  // Navigate to detail page in future
                }}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
