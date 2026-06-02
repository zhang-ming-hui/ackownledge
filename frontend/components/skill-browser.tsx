'use client'

import { useState } from 'react'
import { Search, Filter, ChevronDown } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import type { Skill } from '@/lib/mock-data'

interface SkillBrowserProps {
  skills: Skill[]
  selectedSkillId: string | null
  onSelectSkill: (skill: Skill) => void
  filterValue?: string
  onFilterChange?: (value: string) => void
}

const categories = ['全部', '数据分析', '自动化', '云服务', 'SEO', '数据库', '文档', '媒体处理', '监控', 'DevOps', '安全']

export function SkillBrowser({
  skills,
  selectedSkillId,
  onSelectSkill,
  filterValue,
  onFilterChange,
}: SkillBrowserProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('全部')

  const filteredSkills = skills.filter((skill) => {
    const matchesSearch = skill.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      skill.description.toLowerCase().includes(searchQuery.toLowerCase())
    const matchesCategory = selectedCategory === '全部' || skill.category === selectedCategory
    const matchesFilter = !filterValue || 
      skill.extraction?.platforms.values.includes(filterValue) ||
      skill.extraction?.languages.values.includes(filterValue) ||
      skill.extraction?.actionTypes.values.includes(filterValue)
    return matchesSearch && matchesCategory && matchesFilter
  })

  return (
    <div className="flex h-full flex-col bg-card rounded-xl shadow-sm border border-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-foreground">文档列表</h2>
          <Badge variant="secondary" className="text-xs">
            共 {filteredSkills.length} 篇
          </Badge>
        </div>
        {filterValue && (
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-muted-foreground"
            onClick={() => onFilterChange?.('')}
          >
            清除筛选
          </Button>
        )}
      </div>

      {/* Search and Filter */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="搜索技能名称…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-8 pl-8 text-sm"
          />
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-8 gap-1 text-xs">
              <Filter className="h-3 w-3" />
              {selectedCategory}
              <ChevronDown className="h-3 w-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {categories.map((category) => (
              <DropdownMenuItem
                key={category}
                onClick={() => setSelectedCategory(category)}
                className={cn(
                  'text-sm',
                  selectedCategory === category && 'bg-accent'
                )}
              >
                {category}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Skill List */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <ScrollArea className="h-full">
          <div className="p-2">
          {filteredSkills.map((skill) => (
            <button
              key={skill.id}
              onClick={() => onSelectSkill(skill)}
              className={cn(
                'relative w-full rounded-lg p-3 text-left transition-all hover:bg-muted/50',
                selectedSkillId === skill.id && 'bg-muted/80'
              )}
            >
              {/* Active indicator */}
              {selectedSkillId === skill.id && (
                <div className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-primary" />
              )}

              <div className="pl-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground truncate flex-1">
                    {skill.name}
                  </span>
                  {skill.isExtracted && (
                    <span className="h-2 w-2 rounded-full bg-green-500 shrink-0" />
                  )}
                </div>

                <div className="mt-1 flex items-center gap-2">
                  <Badge 
                    variant="secondary" 
                    className="text-[10px] px-1.5 py-0 h-4"
                  >
                    {skill.category}
                  </Badge>
                  <span className="text-[11px] text-muted-foreground">
                    {skill.owner}
                  </span>
                </div>

                <p className="mt-1.5 text-xs text-muted-foreground line-clamp-1">
                  {skill.description}
                </p>
              </div>
            </button>
          ))}
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
