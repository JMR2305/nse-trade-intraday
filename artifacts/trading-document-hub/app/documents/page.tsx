'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { AppHeader } from '@/components/app-header';
import { DocumentCard } from '@/components/document-card';
import { DocumentTable } from '@/components/document-table';
import { FilterBar } from '@/components/filter-bar';
import { Button } from '@/components/ui/button';
import { Document, FilterOptions } from '@/lib/types';
import { documentService } from '@/lib/services';
import { Plus, Grid3x3, List } from 'lucide-react';

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [filters, setFilters] = useState<FilterOptions>({
    sortBy: 'date',
    sortOrder: 'desc',
  });
  const [viewMode, setViewMode] = useState<'grid' | 'table'>('grid');
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
            All Documents
          </h1>
          <p className="text-muted-foreground">
            Complete library of intraday trading research and analysis documents
          </p>
        </div>

        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
            <FilterBar
              filters={filters}
              onFiltersChange={setFilters}
              showDocumentType={true}
              showSortBy={true}
            />
            <div className="flex gap-2 bg-muted p-1 rounded-lg">
              <Button
                variant={viewMode === 'grid' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('grid')}
                className="px-3"
              >
                <Grid3x3 className="h-4 w-4" />
              </Button>
              <Button
                variant={viewMode === 'table' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('table')}
                className="px-3"
              >
                <List className="h-4 w-4" />
              </Button>
            </div>
          </div>
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
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {documents.map((doc) => (
              <Link key={doc.id} href={`/documents/${doc.slug}`}>
                <DocumentCard
                  document={doc}
                  onClick={() => {}}
                />
              </Link>
            ))}
          </div>
        ) : (
          <DocumentTable documents={documents} />
        )}
      </main>
    </div>
  );
}
