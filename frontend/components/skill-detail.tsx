'use client'

import { useState } from 'react'
import { ExternalLink, FileText, Quote, Tag } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import type { Skill, ExtractionField, MetricField } from '@/lib/mock-data'

interface SkillDetailProps {
  skill: Skill | null
}

interface FieldCardProps {
  icon: string
  label: string
  labelEn: string
  field: ExtractionField | MetricField | undefined
  colorClass: string
  type?: 'default' | 'metric'
  onJudge?: (judgment: 'correct' | 'partial' | 'incorrect') => void
}

function FieldCard({ icon, label, labelEn, field, colorClass, type = 'default', onJudge }: FieldCardProps) {
  const isEmpty = !field || (type === 'default' 
    ? (field as ExtractionField).values.length === 0 
    : (field as MetricField).values.length === 0)

  return (
    <Card className="overflow-hidden">
      <CardHeader className="py-2 px-3 bg-muted/30">
        <div className="flex items-center gap-2">
          <span className="text-sm">{icon}</span>
          <span className="text-xs font-medium text-foreground">{label}</span>
          <span className="text-[10px] text-muted-foreground">({labelEn})</span>
        </div>
      </CardHeader>
      <CardContent className="p-2.5 space-y-2">
        {isEmpty ? (
          <p className="text-sm text-muted-foreground">未抽取到该字段</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-1.5">
              {type === 'default' 
                ? (field as ExtractionField).values.map((value, i) => (
                    <span
                      key={i}
                      className={cn(
                        'px-2 py-0.5 rounded-md text-xs font-medium',
                        colorClass
                      )}
                    >
                      {value}
                    </span>
                  ))
                : (field as MetricField).values.map((metric, i) => (
                    <span
                      key={i}
                      className={cn(
                        'px-2 py-0.5 rounded-md text-xs font-mono font-medium',
                        colorClass
                      )}
                    >
                      {metric.value} {metric.unit}
                    </span>
                  ))
              }
            </div>

            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <Quote className="h-2.5 w-2.5" />
                <span>证据 (Evidence):</span>
              </div>
              <p className="text-[11px] text-foreground/80 bg-muted/50 rounded-md p-1.5 italic line-clamp-2">
                "{field.evidence}"
              </p>
              <div className="flex items-center gap-1 text-[9px] text-muted-foreground">
                <Tag className="h-2 w-2" />
                <span>来源: {field.source}</span>
              </div>
            </div>

            {onJudge && (
              <div className="flex items-center gap-1 pt-1.5 border-t border-border">
                <span className="text-[9px] text-muted-foreground mr-1">评价:</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 px-1.5 text-[9px] text-green-600 hover:text-green-700 hover:bg-green-50"
                  onClick={() => onJudge('correct')}
                >
                  准确
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 px-1.5 text-[9px] text-amber-600 hover:text-amber-700 hover:bg-amber-50"
                  onClick={() => onJudge('partial')}
                >
                  部分准确
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 px-1.5 text-[9px] text-red-600 hover:text-red-700 hover:bg-red-50"
                  onClick={() => onJudge('incorrect')}
                >
                  不准确
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center px-8">
      <div className="w-20 h-20 rounded-full bg-muted/50 flex items-center justify-center mb-4">
        <FileText className="h-10 w-10 text-muted-foreground/50" />
      </div>
      <h3 className="text-lg font-medium text-foreground mb-2">
        选择一个技能查看详情
      </h3>
      <p className="text-sm text-muted-foreground max-w-xs">
        👈 从左侧列表中选择一个技能查看抽取结果
      </p>
    </div>
  )
}

export function SkillDetail({ skill }: SkillDetailProps) {
  const [activeTab, setActiveTab] = useState('extraction')

  if (!skill) {
    return (
      <div className="flex h-full bg-card rounded-xl shadow-sm border border-border">
        <EmptyState />
      </div>
    )
  }

  const { extraction } = skill

  const handleJudge = (field: string, judgment: 'correct' | 'partial' | 'incorrect') => {
    console.log(`[v0] Judgment for ${field}: ${judgment}`)
    // In a real app, this would send to an API
  }

  return (
    <div className="flex h-full flex-col bg-card rounded-xl shadow-sm border border-border overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 border-b border-border">
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-foreground">{skill.name}</h1>
            <div className="mt-2 flex items-center gap-3">
              <Badge variant="secondary">{skill.category}</Badge>
              <span className="text-sm text-muted-foreground">{skill.owner}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={skill.detailUrl} target="_blank" rel="noopener noreferrer" className="gap-1.5">
                <ExternalLink className="h-3.5 w-3.5" />
                详情链接
              </a>
            </Button>
            <Button variant="secondary" size="sm">
              在 IR 系统中查看
            </Button>
          </div>
        </div>

        {/* Summary sentence */}
        {extraction && (
          <p className="mt-4 text-sm text-foreground/90 leading-relaxed bg-muted/30 rounded-lg p-3">
            该技能在{' '}
            <span className="font-medium text-[var(--field-platform-text)]">
              {extraction.platforms.values.join(' / ') || '未知平台'}
            </span>
            {' '}等平台上，使用{' '}
            <span className="font-medium text-[var(--field-language-text)]">
              {extraction.languages.values.join(' / ') || '未知语言'}
            </span>
            ，执行{' '}
            <span className="font-medium text-[var(--field-action-text)]">
              {extraction.actionTypes.values.join(' / ') || '未知操作'}
            </span>
            {' '}操作，面向{' '}
            <span className="font-medium text-[var(--field-domain-text)]">
              {extraction.targetDomains.values.join(' / ') || '未知领域'}
            </span>
            {' '}领域，输出{' '}
            <span className="font-medium text-[var(--field-format-text)]">
              {extraction.outputFormats.values.join(' / ') || '未知格式'}
            </span>
            {' '}格式。
          </p>
        )}
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0">
        <div className="border-b border-border px-5 shrink-0">
          <TabsList className="h-10 bg-transparent gap-4 p-0">
            <TabsTrigger 
              value="extraction" 
              className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2"
            >
              结构化抽取
            </TabsTrigger>
            <TabsTrigger 
              value="raw" 
              className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none px-0 pb-2"
            >
              原始文本
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="extraction" className="flex-1 min-h-0 m-0 data-[state=inactive]:hidden">
          <ScrollArea className="h-full">
            <div className="p-5">
              {extraction ? (
                <div className="grid grid-cols-2 gap-4">
                  <FieldCard
                    icon="🌐"
                    label="平台"
                    labelEn="Platforms"
                    field={extraction.platforms}
                    colorClass="bg-field-platform-bg text-field-platform-text"
                    onJudge={(j) => handleJudge('platforms', j)}
                  />
                  <FieldCard
                    icon="💻"
                    label="编程语言"
                    labelEn="Languages"
                    field={extraction.languages}
                    colorClass="bg-field-language-bg text-field-language-text"
                    onJudge={(j) => handleJudge('languages', j)}
                  />
                  <FieldCard
                    icon="⚡"
                    label="操作类型"
                    labelEn="Action Types"
                    field={extraction.actionTypes}
                    colorClass="bg-field-action-bg text-field-action-text"
                    onJudge={(j) => handleJudge('actionTypes', j)}
                  />
                  <FieldCard
                    icon="🎯"
                    label="目标领域"
                    labelEn="Target Domains"
                    field={extraction.targetDomains}
                    colorClass="bg-field-domain-bg text-field-domain-text"
                    onJudge={(j) => handleJudge('targetDomains', j)}
                  />
                  <FieldCard
                    icon="📄"
                    label="输出格式"
                    labelEn="Output Formats"
                    field={extraction.outputFormats}
                    colorClass="bg-field-format-bg text-field-format-text"
                    onJudge={(j) => handleJudge('outputFormats', j)}
                  />
                  <FieldCard
                    icon="📊"
                    label="性能指标"
                    labelEn="Metrics"
                    field={extraction.metrics}
                    colorClass="bg-field-metric-bg text-field-metric-text"
                    type="metric"
                    onJudge={(j) => handleJudge('metrics', j)}
                  />
                </div>
              ) : (
                <div className="flex items-center justify-center h-full">
                  <p className="text-muted-foreground">该技能尚未完成信息抽取</p>
                </div>
              )}
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="raw" className="flex-1 min-h-0 m-0 data-[state=inactive]:hidden">
          <ScrollArea className="h-full">
            <div className="p-5">
              {extraction?.rawText ? (
                <div className="prose prose-sm max-w-none">
                  <div className="bg-muted/30 rounded-lg p-4 text-sm leading-relaxed">
                    {extraction.rawText}
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-full">
                  <p className="text-muted-foreground">暂无原始文本数据</p>
                </div>
              )}
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  )
}
