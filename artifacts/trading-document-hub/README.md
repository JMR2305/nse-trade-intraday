# Intraday Trade Hub

A professional document management system for intraday trading research, analysis, and market data. The application provides both public-facing document browsing and comprehensive admin controls for managing batches, documents, and uploads.

## Features

### Public Interface
- **Research Documents Library**: Browse and search trading research documents with advanced filtering
- **Document Batches**: View organized collections of documents by release date
- **Advanced Search**: Filter by document type, author, tags, and date range
- **Responsive Design**: Works seamlessly on desktop, tablet, and mobile devices

### Admin Dashboard
- **Dashboard Overview**: Real-time statistics on documents, batches, uploads, and publication rate
- **Batch Management**: Create, edit, and manage document batches with status tracking
- **Document Management**: Full CRUD operations on research documents
- **Upload Tracking**: Monitor file uploads with status tracking (pending, processing, completed, failed)
- **Audit Log**: Track all system activities and changes for compliance
- **Settings**: Configure application endpoints and manage system status

## Technology Stack

- **Framework**: Next.js 16 with React 19
- **Styling**: Tailwind CSS with custom theme
- **UI Components**: shadcn/ui with Radix UI primitives
- **Data Handling**: Service layer abstraction for easy backend integration
- **Type Safety**: Full TypeScript support
- **Date Management**: date-fns for date formatting and calculations

## Project Structure

```
├── app/
│   ├── layout.tsx              # Root layout
│   ├── page.tsx                # Home/documents page
│   ├── documents/page.tsx       # Documents listing
│   ├── batches/page.tsx         # Public batches view
│   └── admin/
│       ├── page.tsx             # Admin dashboard
│       ├── batches/page.tsx      # Manage batches
│       ├── documents/page.tsx    # Manage documents
│       ├── uploads/page.tsx      # Manage uploads
│       ├── audit/page.tsx        # Audit log
│       └── settings/page.tsx     # Admin settings
├── components/
│   ├── ui/                      # shadcn/ui components
│   ├── app-header.tsx           # Navigation header
│   ├── document-card.tsx        # Document display card
│   ├── batch-card.tsx           # Batch display card
│   ├── filter-bar.tsx           # Advanced filtering
│   ├── stat-card.tsx            # Statistics display
│   └── activity-list.tsx        # Activity timeline
├── lib/
│   ├── types.ts                 # TypeScript interfaces
│   ├── mock-data.ts             # Mock data for demo
│   ├── services.ts              # Service layer abstraction
│   └── utils.ts                 # Utility functions
└── public/                       # Static assets
```

## Getting Started

### Installation

```bash
# Install dependencies
pnpm install

# Start development server
pnpm dev

# Open browser
open http://localhost:3000
```

### Navigation

**Public Routes:**
- `/` - Home page with featured documents
- `/documents` - Browse all research documents
- `/batches` - View document batches

**Admin Routes:**
- `/admin` - Dashboard with statistics
- `/admin/batches` - Manage batches
- `/admin/documents` - Manage documents
- `/admin/uploads` - Track uploads
- `/admin/audit` - View audit log
- `/admin/settings` - Configure settings

## Service Layer Architecture

The application uses a service layer pattern that abstracts data operations:

```typescript
// Services provide a consistent interface
import { documentService, batchService } from '@/lib/services'

// Get all published documents
const docs = await documentService.getAll()

// Get by ID
const doc = await documentService.getById('doc-123')

// Create new
await documentService.create({
  title: 'New Doc',
  // ... other fields
})

// Update
await documentService.update('doc-123', { title: 'Updated' })

// Delete
await documentService.delete('doc-123')
```

This design allows you to easily swap mock data with real API calls or database queries without changing component code.

## Mock Data

The application includes comprehensive mock data for demonstration:

- **4 Documents** across multiple types (research, analysis, update, report)
- **3 Batches** with different status states (draft, scheduled, released)
- **4 Uploads** showing various upload states
- **Activity logs** with audit trail entries

All mock data is generated in `lib/mock-data.ts` and can be replaced with real API calls by modifying the services in `lib/services.ts`.

## Customization

### Colors & Theme

Update design tokens in `app/globals.css`:

```css
:root {
  --primary: oklch(0.205 0 0);
  --secondary: oklch(0.97 0 0);
  /* ... more tokens ... */
}
```

### API Integration

To connect to your backend:

1. Update endpoints in `lib/services.ts`
2. Replace mock data calls with real API calls
3. Update error handling as needed

Example:

```typescript
export const documentService = {
  async getAll(filters?: FilterOptions): Promise<Document[]> {
    // Replace with actual API call
    const response = await fetch('/api/documents', {
      method: 'POST',
      body: JSON.stringify(filters)
    })
    return response.json()
  }
}
```

### Adding New Features

1. Create new page in appropriate route folder
2. Add types in `lib/types.ts` if needed
3. Create service methods in `lib/services.ts`
4. Build components using existing UI component library
5. Add navigation link in `components/app-header.tsx`

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari, Chrome Mobile)

## Performance Considerations

- **Code Splitting**: Next.js automatically splits code per route
- **Image Optimization**: Use Next.js Image component
- **Data Fetching**: Service layer enables caching strategies
- **Responsive**: Mobile-first design with Tailwind breakpoints

## Development Tips

- Use `pnpm dev` for hot reload development
- Modify `lib/mock-data.ts` to test with different data
- Update `lib/services.ts` for API integration
- Check component props for customization options
- Use shadcn/ui component variants for styling

## Deployment

### Vercel (Recommended)

```bash
# Push to GitHub
git push

# Deploy on Vercel (automatic from git)
# Environment variables can be set in Vercel dashboard
```

### Self-Hosted

```bash
# Build
pnpm build

# Start
pnpm start
```

## API Contract & Service Layer

All data operations are abstracted through a service layer. To replace mock data with real APIs:

### Service Methods

```typescript
// Document Service
documentService.getAll(filters?: FilterOptions)
documentService.getById(id: string)
documentService.getBySlug(slug: string)
documentService.getByBatchId(batchId: string)
documentService.create(data: Omit<Document, 'id' | 'createdAt' | 'updatedAt'>)
documentService.update(id: string, data: Partial<Document>)
documentService.delete(id: string)

// Batch Service
batchService.getAll()
batchService.getPublished()
batchService.getById(id: string)
batchService.create(data)
batchService.update(id: string, data)
batchService.delete(id: string)

// Upload Service
uploadService.getAll()
uploadService.getById(id: string)
uploadService.getByBatchId(batchId: string)
uploadService.create(data)
uploadService.update(id: string, data)
uploadService.delete(id: string)

// Audit Service
auditService.getAll()
auditService.log(action: string, entityType, entityId, userId, details?)

// Dashboard Service
dashboardService.getStats()
```

### Backend Integration Steps

1. **Environment Variables**
   - No environment variables are required in development
   - For production, add your API endpoints to `.env.local` (not used currently)
   - No client-side secrets are exposed

2. **Replace Mock Data in `/lib/services.ts`**
   - Keep the service interface exactly the same
   - Replace mock array access with `fetch()` calls
   - Maintain the same return types and error handling

3. **Example Migration**
   ```typescript
   // Before (mock)
   async getAll(filters?: FilterOptions): Promise<Document[]> {
     return mockDocuments.filter(...)
   }
   
   // After (API)
   async getAll(filters?: FilterOptions): Promise<Document[]> {
     const response = await fetch('/api/documents', {
       method: 'POST',
       body: JSON.stringify(filters)
     })
     if (!response.ok) throw new Error('Failed to fetch')
     return response.json()
   }
   ```

4. **Authentication** (if needed)
   - Update service layer to add auth headers
   - Components will work unchanged

## Type Definitions

All types are centralized in `/lib/types.ts`:

```typescript
// Core entities
export interface Document { /* ... */ }
export interface Batch { /* ... */ }
export interface Upload { /* ... */ }
export interface AuditLog { /* ... */ }

// Enums (as union types for better DX)
type DocumentType = 'research' | 'analysis' | 'update' | 'report'
type BatchStatus = 'draft' | 'scheduled' | 'released' | 'archived'
type UploadStatus = 'pending' | 'processing' | 'completed' | 'failed'
```

## Centralized Constants

**Document Types:** `research`, `analysis`, `update`, `report`
**Batch Statuses:** `draft`, `scheduled`, `released`, `archived`
**Upload Statuses:** `pending`, `processing`, `completed`, `failed`
**Entities:** `document`, `batch`, `upload`, `settings`

## Replit Handover Guide

### Quick Start

```bash
# 1. Clone the repository
git clone <repository-url>
cd intraday-trade-hub

# 2. Install dependencies
pnpm install

# 3. Start development
pnpm dev

# 4. Open browser
# Visit http://localhost:3000
```

### Project Organization

- **Components** are in `/components` (UI building blocks)
- **Pages/Routes** are in `/app` (Next.js file-based routing)
- **Business Logic** is in `/lib/services.ts` (easy to replace with API calls)
- **Types** are in `/lib/types.ts` (single source of truth)
- **Mock Data** is in `/lib/mock-data.ts` (demo data)
- **Styles** are in `/app/globals.css` (Tailwind design tokens)

### Key Files to Modify

1. **To add new API endpoint**: Update `/lib/services.ts`
2. **To add new page**: Create `/app/your-page/page.tsx`
3. **To add new component**: Create `/components/your-component.tsx`
4. **To change colors**: Update design tokens in `/app/globals.css`
5. **To add to navigation**: Update `/components/app-header.tsx`

### Backend TODO Items

- [ ] Connect to production database (replace mock data in services.ts)
- [ ] Implement authentication (update auth service if needed)
- [ ] Set up file upload handling (update uploadService)
- [ ] Configure audit logging backend
- [ ] Add API error handling and retry logic
- [ ] Implement caching strategies
- [ ] Set up database migrations
- [ ] Add production secrets to .env.production

### Environment Variables

**Development:** No environment variables required (uses mock data)
**Production:** Add your API endpoints (optional - code will work with mock data)

```env
# Example for production (optional)
NEXT_PUBLIC_API_URL=https://api.example.com
NEXT_PUBLIC_STORAGE_URL=https://storage.example.com
```

**Note:** No secrets are required in the frontend. All backend secrets should remain on the server.

## Security Checklist

✅ No hardcoded secrets in source code
✅ No direct backend dependencies (Supabase, R2, AWS)
✅ All data operations use service layer
✅ Mock data is isolated and easy to replace
✅ No incomplete authentication implementations
✅ No fake security patterns
✅ All environment-dependent code is in services
✅ Type-safe throughout

## Code Quality

- **TypeScript**: Full type coverage, no `any` types in business logic
- **Components**: Split into small, reusable pieces
- **Accessibility**: ARIA labels, semantic HTML, keyboard navigation
- **Responsive**: Mobile-first design, works on all devices
- **Performance**: Code splitting per route, optimized renders

## Testing During Development

```bash
# All routes are accessible:
http://localhost:3000                 # Home
http://localhost:3000/documents       # Document listing
http://localhost:3000/documents/[slug] # Document detail
http://localhost:3000/batches         # Batch listing

# Admin routes:
http://localhost:3000/admin            # Dashboard
http://localhost:3000/admin/documents  # Manage documents
http://localhost:3000/admin/batches    # Manage batches
http://localhost:3000/admin/uploads    # Manage uploads
http://localhost:3000/admin/audit      # Audit log
http://localhost:3000/admin/settings   # Settings
```

## License

MIT

## Support

For issues or questions during development, check:
1. Component props in `/components`
2. Service interface in `/lib/services.ts`
3. Type definitions in `/lib/types.ts`
4. Console for debug logs (prefixed with `[v0]`)

---

Built with ❤️ for intraday traders. Ready for production backend integration.
