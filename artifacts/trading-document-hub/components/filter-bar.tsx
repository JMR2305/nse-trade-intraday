'use client';

import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Search, X } from 'lucide-react';
import { FilterOptions } from '@/lib/types';

interface FilterBarProps {
  filters: FilterOptions;
  onFiltersChange: (filters: FilterOptions) => void;
  showDocumentType?: boolean;
  showSortBy?: boolean;
}

export function FilterBar({
  filters,
  onFiltersChange,
  showDocumentType = true,
  showSortBy = true,
}: FilterBarProps) {
  const handleSearchChange = (value: string) => {
    onFiltersChange({ ...filters, searchQuery: value });
  };

  const handleDocumentTypeChange = (value: string) => {
    onFiltersChange({
      ...filters,
      documentType: value === 'all' ? undefined : value,
    });
  };

  const handleSortByChange = (value: string) => {
    onFiltersChange({
      ...filters,
      sortBy: value as 'date' | 'title' | 'relevance',
    });
  };

  const handleSortOrderChange = (value: string) => {
    onFiltersChange({
      ...filters,
      sortOrder: value as 'asc' | 'desc',
    });
  };

  const handleClear = () => {
    onFiltersChange({});
  };

  const hasActiveFilters =
    filters.searchQuery ||
    filters.documentType ||
    filters.tags?.length ||
    filters.author ||
    filters.sortBy;

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search documents..."
            value={filters.searchQuery || ''}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-10"
          />
        </div>
        {hasActiveFilters && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClear}
            className="gap-2"
          >
            <X className="h-4 w-4" />
            Clear
          </Button>
        )}
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        {showDocumentType && (
          <Select value={filters.documentType || 'all'} onValueChange={handleDocumentTypeChange}>
            <SelectTrigger className="w-full sm:w-40">
              <SelectValue placeholder="Document type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              <SelectItem value="research">Research</SelectItem>
              <SelectItem value="analysis">Analysis</SelectItem>
              <SelectItem value="update">Update</SelectItem>
              <SelectItem value="report">Report</SelectItem>
            </SelectContent>
          </Select>
        )}

        {showSortBy && (
          <>
            <Select value={filters.sortBy || 'date'} onValueChange={handleSortByChange}>
              <SelectTrigger className="w-full sm:w-40">
                <SelectValue placeholder="Sort by" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="date">Date</SelectItem>
                <SelectItem value="title">Title</SelectItem>
                <SelectItem value="relevance">Relevance</SelectItem>
              </SelectContent>
            </Select>

            <Select value={filters.sortOrder || 'desc'} onValueChange={handleSortOrderChange}>
              <SelectTrigger className="w-full sm:w-40">
                <SelectValue placeholder="Order" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="desc">Newest first</SelectItem>
                <SelectItem value="asc">Oldest first</SelectItem>
              </SelectContent>
            </Select>
          </>
        )}
      </div>
    </div>
  );
}
