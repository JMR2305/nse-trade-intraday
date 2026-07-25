'use client';

import { Document } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FileText, User, Calendar } from 'lucide-react';

interface DocumentCardProps {
  document: Document;
  onClick?: () => void;
}

export function DocumentCard({ document, onClick }: DocumentCardProps) {
  return (
    <Card
      className="hover:border-primary/50 cursor-pointer transition-all hover:shadow-md"
      onClick={onClick}
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <CardTitle className="line-clamp-2 text-lg">{document.title}</CardTitle>
            <CardDescription className="line-clamp-1 mt-1">
              {document.description}
            </CardDescription>
          </div>
          <Badge variant="secondary" className="whitespace-nowrap">
            {document.documentType}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">
          {document.tags.map((tag) => (
            <Badge key={tag} variant="outline" className="text-xs">
              {tag}
            </Badge>
          ))}
        </div>
        <div className="space-y-2 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <User className="h-4 w-4 shrink-0" />
            <span>{document.author}</span>
          </div>
          <div className="flex items-center gap-2">
            <Calendar className="h-4 w-4 shrink-0" />
            <span>{document.releaseDate.toLocaleDateString()}</span>
          </div>
          {document.pageCount && (
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 shrink-0" />
              <span>{document.pageCount} pages</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
