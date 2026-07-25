'use client';

import { useState, useEffect } from 'react';
import { AppHeader } from '@/components/app-header';
import { BatchCard } from '@/components/batch-card';
import { Button } from '@/components/ui/button';
import { Batch } from '@/lib/types';
import { batchService, documentService } from '@/lib/services';
import { Plus, Copy, Download } from 'lucide-react';

export default function BatchesPage() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const loadBatches = async () => {
      setLoading(true);
      const data = await batchService.getPublished();
      setBatches(data.sort((a, b) => b.releaseDate.getTime() - a.releaseDate.getTime()));
      setLoading(false);
    };
    loadBatches();
  }, []);

  const handleCopyAllLinks = async () => {
    const allDocs = await documentService.getAll({});
    const links = allDocs
      .map((doc) => `${doc.title}: ${typeof window !== 'undefined' ? window.location.origin : ''}/documents/${doc.slug}`)
      .join('\n');
    
    navigator.clipboard.writeText(links);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadBatchManifest = () => {
    const manifest = {
      batches: batches.map((batch) => ({
        id: batch.id,
        title: batch.title,
        releaseDate: batch.releaseDate,
        documentCount: batch.documentCount,
        status: batch.status,
      })),
      generatedAt: new Date().toISOString(),
    };

    const element = document.createElement('a');
    element.setAttribute('href', `data:text/json;charset=utf-8,${encodeURIComponent(JSON.stringify(manifest, null, 2))}`);
    element.setAttribute('download', `batches-manifest-${new Date().toISOString().split('T')[0]}.json`);
    element.style.display = 'none';
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-4">
            <div>
              <h1 className="text-3xl font-bold tracking-tight mb-2">
                Document Batches
              </h1>
              <p className="text-muted-foreground">
                Daily reports and document collections organized by release date
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleCopyAllLinks}
                className="whitespace-nowrap"
              >
                <Copy className="h-4 w-4 mr-2" />
                {copied ? 'Copied!' : 'Copy all links'}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleDownloadBatchManifest}
                className="whitespace-nowrap"
              >
                <Download className="h-4 w-4 mr-2" />
                Download manifest
              </Button>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="text-muted-foreground">Loading batches...</div>
          </div>
        ) : batches.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12">
            <Plus className="h-12 w-12 text-muted-foreground mb-4 opacity-50" />
            <p className="text-muted-foreground">No batches found</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {batches.map((batch) => (
              <BatchCard
                key={batch.id}
                batch={batch}
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
