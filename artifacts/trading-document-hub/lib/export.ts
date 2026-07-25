import { Document, Batch } from './types';

/**
 * Export documents as CSV
 */
export function exportDocumentsAsCSV(documents: Document[]): string {
  const headers = [
    'ID',
    'Title',
    'Type',
    'Author',
    'Release Date',
    'Tags',
    'Pages',
    'Published',
  ];

  const rows = documents.map((doc) => [
    doc.id,
    `"${doc.title.replace(/"/g, '""')}"`, // Escape quotes
    doc.documentType,
    doc.author,
    doc.releaseDate.toISOString().split('T')[0],
    `"${doc.tags.join(', ')}"`,
    doc.pageCount || '',
    doc.isPublished ? 'Yes' : 'No',
  ]);

  const csv = [
    headers.join(','),
    ...rows.map((row) => row.join(',')),
  ].join('\n');

  return csv;
}

/**
 * Export batches as CSV
 */
export function exportBatchesAsCSV(batches: Batch[]): string {
  const headers = [
    'ID',
    'Name',
    'Documents',
    'Release Date',
    'Status',
    'Published',
  ];

  const rows = batches.map((batch) => [
    batch.id,
    `"${batch.name.replace(/"/g, '""')}"`,
    batch.totalDocuments,
    batch.releaseDate.toISOString().split('T')[0],
    batch.status,
    batch.isPublished ? 'Yes' : 'No',
  ]);

  const csv = [
    headers.join(','),
    ...rows.map((row) => row.join(',')),
  ].join('\n');

  return csv;
}

/**
 * Download CSV file
 */
export function downloadCSV(csv: string, filename: string): void {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);

  link.setAttribute('href', url);
  link.setAttribute('download', filename);
  link.style.visibility = 'hidden';

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Export documents as JSON
 */
export function exportDocumentsAsJSON(documents: Document[]): string {
  return JSON.stringify(documents, null, 2);
}

/**
 * Download JSON file
 */
export function downloadJSON(data: string, filename: string): void {
  const blob = new Blob([data], { type: 'application/json;charset=utf-8;' });
  const link = document.createElement('a');
  const url = URL.createObjectURL(blob);

  link.setAttribute('href', url);
  link.setAttribute('download', filename);
  link.style.visibility = 'hidden';

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Generate batch summary report
 */
export function generateBatchSummary(batch: Batch): string {
  const lines = [
    `=== Batch Summary Report ===`,
    `Name: ${batch.name}`,
    `Status: ${batch.status}`,
    `Release Date: ${batch.releaseDate.toLocaleDateString()}`,
    `Documents: ${batch.totalDocuments}`,
    `Published: ${batch.isPublished ? 'Yes' : 'No'}`,
    `\nDescription:`,
    batch.description,
  ];

  if (batch.kimiPrompt) {
    lines.push(`\nKimi Prompt:`);
    lines.push(batch.kimiPrompt);
  }

  return lines.join('\n');
}
