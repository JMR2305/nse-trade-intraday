import Link from 'next/link';
import { Document } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ExternalLink } from 'lucide-react';

interface DocumentTableProps {
  documents: Document[];
}

export function DocumentTable({ documents }: DocumentTableProps) {
  return (
    <div className="rounded-lg border overflow-x-auto">
      <Table>
        <TableHeader className="bg-muted/50">
          <TableRow>
            <TableHead className="font-semibold">Title</TableHead>
            <TableHead className="font-semibold">Type</TableHead>
            <TableHead className="font-semibold">Author</TableHead>
            <TableHead className="font-semibold">Date</TableHead>
            <TableHead className="font-semibold">Pages</TableHead>
            <TableHead className="font-semibold text-right">Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {documents.map((doc) => (
            <TableRow key={doc.id} className="hover:bg-muted/50 transition-colors">
              <TableCell>
                <div className="space-y-1">
                  <div className="font-medium text-sm text-balance">{doc.title}</div>
                  <div className="text-xs text-muted-foreground line-clamp-1">
                    {doc.description}
                  </div>
                </div>
              </TableCell>
              <TableCell>
                <Badge variant="outline" className="text-xs">
                  {doc.type}
                </Badge>
              </TableCell>
              <TableCell className="text-sm">{doc.author}</TableCell>
              <TableCell className="text-sm">{doc.publishedDate}</TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {doc.pageCount}
              </TableCell>
              <TableCell className="text-right">
                <Link href={`/documents/${doc.slug}`}>
                  <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
