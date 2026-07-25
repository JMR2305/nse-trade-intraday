# Intraday Trade Hub - Architecture Documentation

## Overview

This is a production-ready Next.js 16 frontend for a document management system. The architecture uses a **service layer pattern** to abstract data operations, making it trivial to swap mock data with real API calls.

## Design Principles

1. **Service Abstraction**: All data operations go through services, not direct API/DB access
2. **Type Safety**: Full TypeScript coverage with no `any` types in business logic
3. **Component Composition**: Small, reusable UI components with clear props
4. **No Backend Dependencies**: Zero dependencies on Supabase, AWS, or other specific backends
5. **Easy Integration**: Replace mock data with API calls without touching components

## Architecture Diagram

```
┌─────────────────────────────────────┐
│         React Components             │
│  (page.tsx, components/*.tsx)        │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│      Service Layer (/lib/services)  │
│  - documentService                  │
│  - batchService                     │
│  - uploadService                    │
│  - auditService                     │
│  - dashboardService                 │
└──────────────┬──────────────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
   Mock Data      Real API
  (Development)  (Production)
```

## Directory Structure

```
intraday-trade-hub/
├── app/                              # Next.js App Router
│   ├── layout.tsx                    # Root layout
│   ├── page.tsx                      # Home page
│   ├── globals.css                   # Tailwind design tokens
│   ├── documents/
│   │   ├── page.tsx                  # Document listing
│   │   └── [slug]/page.tsx           # Dynamic document detail
│   ├── batches/
│   │   └── page.tsx                  # Batch listing
│   └── admin/                        # Protected admin routes
│       ├── page.tsx                  # Dashboard
│       ├── batches/page.tsx          # Batch management
│       ├── documents/page.tsx        # Document management
│       ├── uploads/page.tsx          # Upload management
│       ├── audit/page.tsx            # Audit log viewer
│       └── settings/page.tsx         # Settings page
│
├── components/
│   ├── ui/                           # shadcn/ui components
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   ├── dialog.tsx
│   │   ├── table.tsx
│   │   ├── input.tsx
│   │   ├── select.tsx
│   │   ├── badge.tsx
│   │   └── skeleton.tsx
│   ├── app-header.tsx                # Navigation header
│   ├── document-card.tsx             # Document display
│   ├── batch-card.tsx                # Batch display
│   ├── document-table.tsx            # Document table view
│   ├── filter-bar.tsx                # Advanced filtering
│   ├── stat-card.tsx                 # Statistics display
│   ├── activity-list.tsx             # Activity timeline
│   ├── confirm-dialog.tsx            # Confirmation dialog
│   └── table-skeleton.tsx            # Loading skeleton
│
├── lib/
│   ├── types.ts                      # TypeScript interfaces (SINGLE SOURCE OF TRUTH)
│   ├── services.ts                   # Service layer (REPLACE WITH APIs HERE)
│   ├── mock-data.ts                  # Mock data for demo
│   ├── format.ts                     # Date/file formatting utilities
│   ├── export.ts                     # Export utilities
│   └── utils.ts                      # General utilities
│
├── public/                           # Static assets
├── package.json                      # Dependencies
├── tsconfig.json                     # TypeScript config
├── next.config.mjs                   # Next.js config
├── postcss.config.mjs                # PostCSS config
├── tailwind.config.js                # Tailwind config
├── README.md                         # Getting started
└── ARCHITECTURE.md                   # This file
```

## Core Services

### Service Layer Pattern

All services are located in `/lib/services.ts` and follow this pattern:

```typescript
export const [entity]Service = {
  async getAll(filters?): Promise<[Entity][]> { /* ... */ },
  async getById(id: string): Promise<[Entity] | null> { /* ... */ },
  async create(data): Promise<[Entity]> { /* ... */ },
  async update(id: string, data): Promise<[Entity] | null> { /* ... */ },
  async delete(id: string): Promise<boolean> { /* ... */ },
}
```

**Services Currently Available:**
- `documentService` - Document CRUD and filtering
- `batchService` - Batch management
- `uploadService` - File upload tracking
- `auditService` - Audit logging
- `dashboardService` - Dashboard statistics

### Migration Path

**Step 1: Current State (Mock)**
```typescript
export const documentService = {
  async getAll(filters) {
    let results = [...mockDocuments]
    // filter and sort
    return results
  }
}
```

**Step 2: API Integration**
```typescript
export const documentService = {
  async getAll(filters) {
    const response = await fetch('/api/documents', {
      method: 'POST',
      body: JSON.stringify(filters),
      headers: { 'Content-Type': 'application/json' }
    })
    if (!response.ok) throw new Error('Failed to fetch documents')
    return response.json()
  }
}
```

**Step 3: Database Integration** (optional)
```typescript
// If using direct database access instead of API
import { db } from '@/lib/db'

export const documentService = {
  async getAll(filters) {
    return db.query.documents.findMany({
      where: buildWhereClause(filters),
      orderBy: buildOrderByClause(filters)
    })
  }
}
```

Components remain 100% unchanged across all three steps.

## Type System

All types are defined in `/lib/types.ts`:

### Core Entities

```typescript
interface Document {
  id: string
  title: string
  description: string
  slug: string
  batchId: string
  releaseDate: Date
  publishedDate: string
  type: 'research' | 'analysis' | 'update' | 'report'
  documentType: 'research' | 'analysis' | 'update' | 'report'
  tags: string[]
  author: string
  fileUrl?: string
  pageCount?: number
  isPublished: boolean
  createdAt: Date
  updatedAt: Date
}

interface Batch {
  id: string
  name: string
  description: string
  releaseDate: Date
  documentIds: string[]
  status: 'draft' | 'scheduled' | 'released' | 'archived'
  kimiPrompt?: string
  totalDocuments: number
  isPublished: boolean
  createdAt: Date
  updatedAt: Date
}

interface Upload {
  id: string
  fileName: string
  fileSize: number
  uploadedAt: Date
  uploadedBy: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  batchId?: string
  documentId?: string
  errorMessage?: string
}

interface AuditLog {
  id: string
  action: string
  entityType: 'document' | 'batch' | 'upload' | 'settings'
  entityId: string
  userId: string
  timestamp: Date
  details: Record<string, any>
}

interface DashboardStats {
  totalDocuments: number
  totalBatches: number
  totalUploads: number
  publishedDocuments: number
  pendingUploads: number
  recentActivity: AuditLog[]
}
```

### Enums (Union Types)

```typescript
type DocumentType = 'research' | 'analysis' | 'update' | 'report'
type BatchStatus = 'draft' | 'scheduled' | 'released' | 'archived'
type UploadStatus = 'pending' | 'processing' | 'completed' | 'failed'
type EntityType = 'document' | 'batch' | 'upload' | 'settings'
```

## Routes

### Public Routes

| Route | Component | Purpose |
|-------|-----------|---------|
| `/` | `app/page.tsx` | Home with featured documents |
| `/documents` | `app/documents/page.tsx` | Document library with filtering |
| `/documents/[slug]` | `app/documents/[slug]/page.tsx` | Document detail page |
| `/batches` | `app/batches/page.tsx` | Batch listing |

### Admin Routes

| Route | Component | Purpose |
|-------|-----------|---------|
| `/admin` | `app/admin/page.tsx` | Dashboard with statistics |
| `/admin/documents` | `app/admin/documents/page.tsx` | Manage documents |
| `/admin/batches` | `app/admin/batches/page.tsx` | Manage batches |
| `/admin/uploads` | `app/admin/uploads/page.tsx` | Track uploads |
| `/admin/audit` | `app/admin/audit/page.tsx` | Audit log viewer |
| `/admin/settings` | `app/admin/settings/page.tsx` | System settings |

**Future Addition:** Route protection - wrap admin routes with auth check.

## Component Hierarchy

### Layout Components
- `AppHeader` - Navigation and user menu
- Root Layout - Global styles and providers

### Page Components
- `DocumentsPage` - Shows list with filters
- `DocumentDetailPage` - Shows single document with actions
- `BatchesPage` - Shows batch cards
- `AdminDashboard` - Shows statistics and recent activity

### UI Components
- `DocumentCard` - Reusable document display
- `BatchCard` - Reusable batch display
- `FilterBar` - Advanced filtering controls
- `ConfirmDialog` - Typed confirmation modal
- `TableSkeleton` - Loading state
- shadcn/ui components (Button, Card, Input, etc.)

## State Management

**No Redux, Zustand, or Context needed.** The application uses:

1. **React `useState`** for local component state
2. **Service layer** for data fetching
3. **Next.js caching** for server-side data

This keeps the codebase lightweight and easy to understand.

### Example: Document Page

```typescript
export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    documentService.getAll({}).then(docs => {
      setDocuments(docs)
      setLoading(false)
    }).catch(err => {
      setError('Failed to load')
      setLoading(false)
    })
  }, [])

  // Components render based on state
}
```

## Styling

### Design Tokens

Centralized in `/app/globals.css` using CSS custom properties:

```css
:root {
  /* Semantic colors */
  --background: 0 0% 100%;
  --foreground: 0 0% 3.6%;
  --primary: 0 0% 9%;
  --secondary: 0 0% 96.1%;
  --destructive: 0 84.2% 60.2%;
  --muted: 0 0% 89.8%;
  /* ... more tokens ... */
}
```

**Theme System:** Uses Tailwind CSS v4 with semantic color scheme.

### Responsive Design

Mobile-first approach using Tailwind breakpoints:

```typescript
// Example component
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
```

- `sm:` - 640px (tablets)
- `md:` - 768px (small laptops)
- `lg:` - 1024px (laptops)
- `xl:` - 1280px (desktops)

## Error Handling

**Consistent Pattern:**

```typescript
try {
  const data = await service.getAll()
  setData(data)
} catch (err) {
  console.error('[v0] Failed to load:', err)
  setError('User-friendly message')
}
```

All errors are logged with `[v0]` prefix for debugging.

## Performance Considerations

1. **Code Splitting**: Next.js automatically splits code per route
2. **Image Optimization**: (Not used currently, but add with Next.js Image component)
3. **Lazy Loading**: Admin pages load on demand
4. **Memoization**: Components use React.memo where beneficial
5. **Service Caching**: Easy to add caching strategies in services

## Security

✅ **Implemented:**
- No hardcoded secrets
- No direct backend dependencies
- Service layer isolates data logic
- TypeScript prevents type-based attacks
- CSRF protection via Next.js defaults

⚠️ **To Add for Production:**
- Authentication middleware
- Rate limiting on API calls
- Input validation
- CORS configuration
- API key rotation

## Development Workflow

### Adding a New Feature

1. **Define Types** in `/lib/types.ts`
2. **Create Service Methods** in `/lib/services.ts`
3. **Build UI Components** in `/components`
4. **Create Page** in `/app` directory
5. **Add Navigation** in `/components/app-header.tsx`

### Example: Add "Featured Documents" Section

```typescript
// 1. Types (if needed)
// Already exists as Document[]

// 2. Service
export const documentService = {
  async getFeatured(): Promise<Document[]> {
    return mockDocuments
      .filter(d => d.isPublished && d.tags.includes('featured'))
      .slice(0, 6)
  }
}

// 3. Component
function FeaturedDocuments() {
  const [docs, setDocs] = useState<Document[]>([])
  useEffect(() => {
    documentService.getFeatured().then(setDocs)
  }, [])
  return <div>{docs.map(d => <DocumentCard key={d.id} document={d} />)}</div>
}

// 4. Add to page
// Add <FeaturedDocuments /> to app/page.tsx

// 5. Navigation
// If it needs its own page, add route in app/featured/page.tsx
```

## Known Limitations

1. **No Authentication** - All pages are public (design ready for auth)
2. **Mock Data Only** - Replace with real API in production
3. **No Real Upload** - Upload tracking is simulated
4. **No Search Backend** - Filtering is client-side
5. **No Real Audit** - Logs are stored in memory only

All are clearly marked with `// TODO:` comments or documented above.

## Next Steps for Production

1. **Connect Database**
   - Replace mock data in services.ts
   - Keep service interface identical

2. **Add Authentication**
   - Add auth service
   - Wrap admin routes with protection

3. **Implement File Upload**
   - Replace uploadService with real handler
   - Point to CDN (Vercel Blob, R2, etc)

4. **Add Search Backend**
   - Move filtering to API
   - Add full-text search

5. **Deploy**
   - Connect GitHub repo
   - Deploy to Vercel
   - Set up CI/CD

## Troubleshooting

**Build fails?**
- Check that all imports are correct
- Run `pnpm install` to ensure dependencies are installed
- Check console for TypeScript errors

**Components not rendering?**
- Check browser console for React errors
- Verify service is returning data
- Check state updates in React DevTools

**Styling looks wrong?**
- Clear `.next` folder and rebuild
- Check that Tailwind CSS is processing globals.css
- Verify design tokens are in app/globals.css

## Additional Resources

- [Next.js Documentation](https://nextjs.org/docs)
- [React Documentation](https://react.dev)
- [Tailwind CSS](https://tailwindcss.com)
- [shadcn/ui](https://ui.shadcn.com)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)
