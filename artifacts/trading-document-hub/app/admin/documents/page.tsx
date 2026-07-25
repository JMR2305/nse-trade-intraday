'use client';

import { useState, useEffect } from 'react';
import { AppHeader } from '@/components/app-header';
import { ConfirmDialog } from '@/components/confirm-dialog';
import { TableSkeleton } from '@/components/table-skeleton';
import { Document } from '@/lib/types';
import { documentService, auditService } from '@/lib/services';
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
import { Plus, Edit, Trash2, AlertCircle } from 'lucide-react';

export default function AdminDocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const loadDocuments = async () => {
      try {
        setLoading(true);
        setError(null);
        const allDocs = await documentService.getAll({});
        setDocuments(allDocs);
      } catch (err) {
        setError('Failed to load documents');
        console.error('[v0] Error loading documents:', err);
      } finally {
        setLoading(false);
      }
    };
    loadDocuments();
  }, []);

  const handleDeleteClick = (docId: string) => {
    setSelectedDocId(docId);
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!selectedDocId) return;
    
    try {
      setIsDeleting(true);
      await documentService.delete(selectedDocId);
      await auditService.log('delete', 'document', selectedDocId, 'admin');
      setDocuments(documents.filter((doc) => doc.id !== selectedDocId));
      setDeleteDialogOpen(false);
      setSelectedDocId(null);
    } catch (err) {
      setError('Failed to delete document');
      console.error('[v0] Error deleting document:', err);
    } finally {
      setIsDeleting(false);
    }
  };

  const selectedDoc = documents.find((d) => d.id === selectedDocId);

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 md:py-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <div className="flex-1">
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight mb-2">
              Manage Documents
            </h1>
            <p className="text-muted-foreground text-sm md:text-base">
              Create, edit, and delete research documents
            </p>
          </div>
          <Button className="gap-2 w-full sm:w-auto">
            <Plus className="h-4 w-4" />
            New Document
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
        ) : documents.length === 0 ? (
          <div className="border rounded-lg p-12 text-center">
            <p className="text-muted-foreground mb-4">No documents found</p>
            <Button className="gap-2">
              <Plus className="h-4 w-4" />
              Create First Document
            </Button>
          </div>
        ) : (
          <div className="border rounded-lg overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[200px]">Title</TableHead>
                  <TableHead className="min-w-[100px]">Type</TableHead>
                  <TableHead className="min-w-[120px]">Author</TableHead>
                  <TableHead className="min-w-[100px]">Release Date</TableHead>
                  <TableHead className="min-w-[80px]">Status</TableHead>
                  <TableHead className="text-right min-w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell className="font-medium line-clamp-1">
                      {doc.title}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{doc.documentType}</Badge>
                    </TableCell>
                    <TableCell className="text-sm">{doc.author}</TableCell>
                    <TableCell className="text-sm">
                      {doc.releaseDate.toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <Badge variant={doc.isPublished ? 'default' : 'secondary'}>
                        {doc.isPublished ? 'Published' : 'Draft'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button 
                          variant="ghost" 
                          size="sm"
                          aria-label={`Edit ${doc.title}`}
                        >
                          <Edit className="h-4 w-4" />
                          <span className="sr-only">Edit</span>
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDeleteClick(doc.id)}
                          aria-label={`Delete ${doc.title}`}
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
          title="Delete Document"
          description={`Are you sure you want to delete "${selectedDoc?.title}"? This action cannot be undone.`}
          confirmText="Delete"
          cancelText="Cancel"
          variant="destructive"
          isLoading={isDeleting}
          onConfirm={handleConfirmDelete}
          onCancel={() => {
            setDeleteDialogOpen(false);
            setSelectedDocId(null);
          }}
        />
      </main>
    </div>
  );
}
