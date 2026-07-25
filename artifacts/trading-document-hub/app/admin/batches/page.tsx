'use client';

import { useState, useEffect } from 'react';
import { AppHeader } from '@/components/app-header';
import { ConfirmDialog } from '@/components/confirm-dialog';
import { TableSkeleton } from '@/components/table-skeleton';
import { Batch } from '@/lib/types';
import { batchService, auditService } from '@/lib/services';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Plus, Edit, Trash2, Eye, AlertCircle } from 'lucide-react';

export default function AdminBatchesPage() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const loadBatches = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await batchService.getAll();
        setBatches(data);
      } catch (err) {
        setError('Failed to load batches');
        console.error('[v0] Error loading batches:', err);
      } finally {
        setLoading(false);
      }
    };
    loadBatches();
  }, []);

  const handleDeleteClick = (batchId: string) => {
    setSelectedBatchId(batchId);
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!selectedBatchId) return;

    try {
      setIsDeleting(true);
      await batchService.delete(selectedBatchId);
      await auditService.log('delete', 'batch', selectedBatchId, 'admin');
      setBatches(batches.filter((batch) => batch.id !== selectedBatchId));
      setDeleteDialogOpen(false);
      setSelectedBatchId(null);
    } catch (err) {
      setError('Failed to delete batch');
      console.error('[v0] Error deleting batch:', err);
    } finally {
      setIsDeleting(false);
    }
  };

  const statusColors: Record<string, any> = {
    draft: 'outline',
    scheduled: 'secondary',
    released: 'default',
    archived: 'outline',
  };

  const selectedBatch = batches.find((b) => b.id === selectedBatchId);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 md:py-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <div className="flex-1">
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight mb-2">
              Manage Batches
            </h1>
            <p className="text-muted-foreground text-sm md:text-base">
              Create and manage document batches
            </p>
          </div>
          <Button className="gap-2 w-full sm:w-auto">
            <Plus className="h-4 w-4" />
            New Batch
          </Button>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-destructive/10 border border-destructive rounded-lg flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-destructive">{error}</p>
              <p className="text-sm text-destructive/80 mt-1">
                Please try refreshing the page or contact support if the problem persists.
              </p>
            </div>
          </div>
        )}

        {loading ? (
          <TableSkeleton columns={6} rows={5} />
        ) : batches.length === 0 ? (
          <div className="border rounded-lg p-12 text-center">
            <p className="text-muted-foreground mb-4">No batches found</p>
            <Button className="gap-2">
              <Plus className="h-4 w-4" />
              Create First Batch
            </Button>
          </div>
        ) : (
          <div className="border rounded-lg overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[180px]">Name</TableHead>
                  <TableHead className="min-w-[80px]">Documents</TableHead>
                  <TableHead className="min-w-[100px]">Release Date</TableHead>
                  <TableHead className="min-w-[90px]">Status</TableHead>
                  <TableHead className="min-w-[80px]">Published</TableHead>
                  <TableHead className="text-right min-w-[120px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {batches.map((batch) => (
                  <TableRow key={batch.id}>
                    <TableCell className="font-medium line-clamp-1">
                      {batch.name}
                    </TableCell>
                    <TableCell className="text-sm">
                      {batch.totalDocuments}
                    </TableCell>
                    <TableCell className="text-sm">
                      {batch.releaseDate.toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusColors[batch.status]}>
                        {batch.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={batch.isPublished ? 'default' : 'secondary'}>
                        {batch.isPublished ? 'Yes' : 'No'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button 
                          variant="ghost" 
                          size="sm"
                          aria-label={`View ${batch.name}`}
                        >
                          <Eye className="h-4 w-4" />
                          <span className="sr-only">View</span>
                        </Button>
                        <Button 
                          variant="ghost" 
                          size="sm"
                          aria-label={`Edit ${batch.name}`}
                        >
                          <Edit className="h-4 w-4" />
                          <span className="sr-only">Edit</span>
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDeleteClick(batch.id)}
                          aria-label={`Delete ${batch.name}`}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                          <span className="sr-only">Delete</span>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <ConfirmDialog
          open={deleteDialogOpen}
          title="Delete Batch"
          description={`Are you sure you want to delete "${selectedBatch?.name}"? This will also remove all associated documents. This action cannot be undone.`}
          confirmText="Delete"
          cancelText="Cancel"
          variant="destructive"
          isLoading={isDeleting}
          onConfirm={handleConfirmDelete}
          onCancel={() => {
            setDeleteDialogOpen(false);
            setSelectedBatchId(null);
          }}
        />
      </main>
    </div>
  );
}
