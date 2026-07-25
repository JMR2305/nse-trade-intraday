import { Document, Batch, Upload, AuditLog, DashboardStats } from './types';

const now = new Date();

const formatDateString = (date: Date) => {
  return date.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' });
};

const generateSlug = (title: string) => {
  return title
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-');
};

export const mockDocuments: Document[] = [
  {
    id: 'doc-1',
    title: 'Morning Market Analysis - Tech Sector',
    description: 'Comprehensive analysis of tech stocks including AAPL, MSFT, and NVDA with intraday trading signals.',
    slug: 'morning-market-analysis-tech-sector',
    batchId: 'batch-1',
    releaseDate: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
    publishedDate: formatDateString(new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000)),
    type: 'analysis',
    documentType: 'analysis',
    tags: ['tech', 'stocks', 'morning'],
    author: 'John Smith',
    pageCount: 12,
    isPublished: true,
    createdAt: new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000),
    updatedAt: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
  },
  {
    id: 'doc-2',
    title: 'Intraday Trading Signals Report',
    description: 'Real-time trading signals and entry/exit points for major indices.',
    slug: 'intraday-trading-signals-report',
    batchId: 'batch-1',
    releaseDate: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
    publishedDate: formatDateString(new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000)),
    type: 'report',
    documentType: 'report',
    tags: ['signals', 'indices', 'trading'],
    author: 'Sarah Johnson',
    pageCount: 8,
    isPublished: true,
    createdAt: new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000),
    updatedAt: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
  },
  {
    id: 'doc-3',
    title: 'Earnings Report Update',
    description: 'Latest earnings announcements and their market impact.',
    slug: 'earnings-report-update',
    batchId: 'batch-2',
    releaseDate: new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000),
    publishedDate: formatDateString(new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000)),
    type: 'update',
    documentType: 'update',
    tags: ['earnings', 'updates', 'market'],
    author: 'Mike Chen',
    pageCount: 5,
    isPublished: true,
    createdAt: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
    updatedAt: new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000),
  },
  {
    id: 'doc-4',
    title: 'Weekly Market Research Summary',
    description: 'Aggregated research insights and trading opportunities for the week.',
    slug: 'weekly-market-research-summary',
    batchId: 'batch-2',
    releaseDate: new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000),
    publishedDate: formatDateString(new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000)),
    type: 'research',
    documentType: 'research',
    tags: ['research', 'weekly', 'summary'],
    author: 'Emma Wilson',
    pageCount: 15,
    isPublished: true,
    createdAt: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
    updatedAt: new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000),
  },
];

export const mockBatches: Batch[] = [
  {
    id: 'batch-1',
    name: 'Daily Report - July 23',
    title: 'Daily Report - July 23',
    description: 'Complete daily market analysis and trading signals.',
    releaseDate: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
    documentIds: ['doc-1', 'doc-2'],
    status: 'released',
    kimiPrompt: 'Summarize the key trading signals and market opportunities from these documents.',
    totalDocuments: 2,
    documentCount: 2,
    isPublished: true,
    createdAt: new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000),
    updatedAt: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
  },
  {
    id: 'batch-2',
    name: 'Daily Report - July 24',
    title: 'Daily Report - July 24',
    description: 'Earnings updates and market reaction analysis.',
    releaseDate: new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000),
    documentIds: ['doc-3', 'doc-4'],
    status: 'released',
    kimiPrompt: 'Analyze the earnings impacts and provide trading recommendations.',
    totalDocuments: 2,
    documentCount: 2,
    isPublished: true,
    createdAt: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
    updatedAt: new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000),
  },
  {
    id: 'batch-3',
    name: 'Daily Report - July 25',
    description: 'Pre-market analysis and sector rotation.',
    releaseDate: new Date(now),
    documentIds: [],
    status: 'scheduled',
    kimiPrompt: 'Focus on pre-market trends and sector rotation opportunities.',
    totalDocuments: 0,
    isPublished: false,
    createdAt: new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000),
    updatedAt: new Date(now.getTime() - 12 * 60 * 60 * 1000),
  },
];

export const mockUploads: Upload[] = [
  {
    id: 'upload-1',
    fileName: 'market-analysis-07-23.pdf',
    fileSize: 2048576,
    uploadedAt: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
    uploadedBy: 'admin@example.com',
    status: 'completed',
    batchId: 'batch-1',
    documentId: 'doc-1',
  },
  {
    id: 'upload-2',
    fileName: 'trading-signals-07-23.pdf',
    fileSize: 1024576,
    uploadedAt: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
    uploadedBy: 'admin@example.com',
    status: 'completed',
    batchId: 'batch-1',
    documentId: 'doc-2',
  },
  {
    id: 'upload-3',
    fileName: 'earnings-update-07-24.pdf',
    fileSize: 512000,
    uploadedAt: new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000),
    uploadedBy: 'admin@example.com',
    status: 'completed',
    batchId: 'batch-2',
    documentId: 'doc-3',
  },
  {
    id: 'upload-4',
    fileName: 'new-research.pdf',
    fileSize: 3145728,
    uploadedAt: new Date(now.getTime() - 2 * 60 * 60 * 1000),
    uploadedBy: 'analyst@example.com',
    status: 'processing',
  },
];

export const mockAuditLogs: AuditLog[] = [
  {
    id: 'log-1',
    action: 'published',
    entityType: 'batch',
    entityId: 'batch-1',
    userId: 'admin@example.com',
    timestamp: new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000),
    details: { status: 'draft', newStatus: 'released' },
  },
  {
    id: 'log-2',
    action: 'created',
    entityType: 'batch',
    entityId: 'batch-3',
    userId: 'admin@example.com',
    timestamp: new Date(now.getTime() - 1 * 24 * 60 * 60 * 1000),
    details: { name: 'Daily Report - July 25' },
  },
  {
    id: 'log-3',
    action: 'uploaded',
    entityType: 'upload',
    entityId: 'upload-4',
    userId: 'analyst@example.com',
    timestamp: new Date(now.getTime() - 2 * 60 * 60 * 1000),
    details: { fileName: 'new-research.pdf', fileSize: 3145728 },
  },
];

export const mockDashboardStats: DashboardStats = {
  totalDocuments: 4,
  totalBatches: 3,
  totalUploads: 4,
  publishedDocuments: 4,
  pendingUploads: 1,
  recentActivity: mockAuditLogs.slice(0, 5),
};
