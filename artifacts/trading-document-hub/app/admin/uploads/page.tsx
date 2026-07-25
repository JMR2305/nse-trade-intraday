'use client';

import { useState, useEffect } from 'react';
import { AppHeader } from '@/components/app-header';
import { ConfirmDialog } from '@/components/confirm-dialog';
import { TableSkeleton } from '@/components/table-skeleton';
import { Upload } from '@/lib/types';
import { uploadService, auditService } from '@/lib/services';
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
import { Plus, Download, Trash2, AlertCircle } from 'lucide-react';

export default function AdminUploadsPage() {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedUploadId, setSelectedUploadId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const loadUploads = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await uploadService.getAll();
        setUploads(data);
      } catch (err) {
        setError('Failed to load uploads');
        console.error('[v0] Error loading uploads:', err);
      } finally {
        setLoading(false);
      }
    };
    loadUploads();
  }, []);

  const handleDeleteClick = (uploadId: string) => {
    setSelectedUploadId(uploadId);
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!selectedUploadId) return;

    try {
      setIsDeleting(true);
      await uploadService.delete(selectedUploadId);
      await auditService.log('delete', 'upload', selectedUploadId, 'admin');
      setUploads(uploads.filter((upload) => upload.id !== selectedUploadId));
      setDeleteDialogOpen(false);
      setSelectedUploadId(null);
    } catch (err) {
      setError('Failed to delete upload');
      console.error('[v0] Error deleting upload:', err);
    } finally {
      setIsDeleting(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const statusColors: Record<string, any> = {
    pending: 'secondary',
    processing: 'outline',
    completed: 'default',
    failed: 'destructive',
  };

  const selectedUpload = uploads.find((u) => u.id === selectedUploadId);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 md:py-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <div className="flex-1">
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight mb-2">
              Manage Uploads
            </h1>
            <p className="text-muted-foreground text-sm md:text-base">
              Track and manage uploaded files
            </p>
          </div>
          <Button className="gap-2 w-full sm:w-auto">
            <Plus className="h-4 w-4" />
            Upload File
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
        ) : uploads.length === 0 ? (
          <div className="border rounded-lg p-12 text-center">
            <p className="text-muted-foreground mb-4">No uploads found</p>
            <Button className="gap-2">
              <Plus className="h-4 w-4" />
              Upload Your First File
            </Button>
          </div>
        ) : (
          <div className="border rounded-lg overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[180px]">File Name</TableHead>
                  <TableHead className="min-w-[80px]">Size</TableHead>
                  <TableHead className="min-w-[120px]">Uploaded By</TableHead>
                  <TableHead className="min-w-[100px]">Upload Date</TableHead>
                  <TableHead className="min-w-[80px]">Status</TableHead>
                  <TableHead className="text-right min-w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {uploads.map((upload) => (
                  <TableRow key={upload.id}>
                    <TableCell className="font-medium line-clamp-1">
                      {upload.fileName}
                    </TableCell>
                    <TableCell className="text-sm">
                      {formatFileSize(upload.fileSize)}
                    </TableCell>
                    <TableCell className="text-sm">
                      {upload.uploadedBy}
                    </TableCell>
                    <TableCell className="text-sm">
                      {upload.uploadedAt.toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <Badge variant={statusColors[upload.status]}>
                        {upload.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button 
                          variant="ghost" 
                          size="sm"
                          aria-label={`Download ${upload.fileName}`}
                        >
                          <Download className="h-4 w-4" />
                          <span className="sr-only">Download</span>
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDeleteClick(upload.id)}
                          aria-label={`Delete ${upload.fileName}`}
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
          title="Delete Upload"
          description={`Are you sure you want to delete "${selectedUpload?.fileName}"? This action cannot be undone.`}
          confirmText="Delete"
          cancelText="Cancel"
          variant="destructive"
          isLoading={isDeleting}
          onConfirm={handleConfirmDelete}
          onCancel={() => {
            setDeleteDialogOpen(false);
            setSelectedUploadId(null);
          }}
        />
      </main>
    </div>
  );
}
