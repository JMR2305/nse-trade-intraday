'use client';

import { Batch } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Calendar, FileText } from 'lucide-react';

interface BatchCardProps {
  batch: Batch;
  onClick?: () => void;
}

const statusColors: Record<string, string> = {
  draft: 'outline',
  scheduled: 'secondary',
  released: 'default',
  archived: 'outline',
};

export function BatchCard({ batch, onClick }: BatchCardProps) {
  return (
    <Card
      className="hover:border-primary/50 cursor-pointer transition-all hover:shadow-md"
      onClick={onClick}
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <CardTitle className="line-clamp-2 text-lg">{batch.name}</CardTitle>
            <CardDescription className="line-clamp-1 mt-1">
              {batch.description}
            </CardDescription>
          </div>
          <Badge variant={statusColors[batch.status] as any} className="whitespace-nowrap">
            {batch.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="flex items-center gap-2 text-muted-foreground">
            <FileText className="h-4 w-4 shrink-0" />
            <span>{batch.totalDocuments} documents</span>
          </div>
          <div className="flex items-center gap-2 text-muted-foreground">
            <Calendar className="h-4 w-4 shrink-0" />
            <span>{batch.releaseDate.toLocaleDateString()}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
