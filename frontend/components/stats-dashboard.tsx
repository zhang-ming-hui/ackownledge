'use client'

import { BarChart3, TrendingUp, CheckCircle2, XCircle, AlertCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import type { CoverageStats, HotValue, EvaluationMetrics, ManualJudgment } from '@/lib/mock-data'

interface StatsDashboardProps {
  coverageStats: CoverageStats[]
  hotValues: Record<string, HotValue[]>
  evaluation: EvaluationMetrics
  judgments: ManualJudgment
  onHotValueClick?: (field: string, value: string) => void
}

function getProgressColor(percentage: number) {
  if (percentage >= 50) return 'bg-green-500'
  if (percentage >= 20) return 'bg-amber-500'
  return 'bg-red-500'
}

function getFieldColor(field: string) {
  const colors: Record<string, string> = {
    platforms: 'bg-field-platform-bg text-field-platform-text',
    languages: 'bg-field-language-bg text-field-language-text',
    actionTypes: 'bg-field-action-bg text-field-action-text',
    targetDomains: 'bg-field-domain-bg text-field-domain-text',
    outputFormats: 'bg-field-format-bg text-field-format-text',
    metrics: 'bg-field-metric-bg text-field-metric-text',
  }
  return colors[field] || 'bg-muted text-muted-foreground'
}

export function StatsDashboard({
  coverageStats,
  hotValues,
  evaluation,
  judgments,
  onHotValueClick,
}: StatsDashboardProps) {
  const completeCount = coverageStats.filter(s => s.percentage >= 50).length
  const noExtraction = coverageStats.reduce((acc, s) => acc + (1000 - s.extracted), 0) / coverageStats.length

  return (
    <ScrollArea className="h-full">
      <div className="space-y-4 p-1">
        {/* Coverage Stats */}
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-primary" />
              抽取覆盖率
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-3">
            {coverageStats.map((stat) => (
              <div key={stat.field} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{stat.fieldLabel}</span>
                  <span className="font-mono font-medium">
                    {stat.percentage.toFixed(1)}%
                    <span className="text-muted-foreground ml-1">
                      ({stat.extracted}/{stat.total})
                    </span>
                  </span>
                </div>
                <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
                  <div
                    className={cn('h-full rounded-full transition-all', getProgressColor(stat.percentage))}
                    style={{ width: `${stat.percentage}%` }}
                  />
                </div>
              </div>
            ))}
            
            <div className="pt-2 border-t border-border space-y-1 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">5项以上完整</span>
                <span className="font-medium text-green-600">312 篇</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">无抽取结果</span>
                <span className="font-medium text-red-600">28 篇</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Hot Values */}
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-primary" />
              热门抽取值
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-3">
            {Object.entries(hotValues).map(([field, values]) => {
              const fieldLabel = {
                platforms: '平台',
                languages: '语言',
                actionTypes: '操作',
              }[field] || field

              return (
                <div key={field} className="space-y-1.5">
                  <span className="text-xs text-muted-foreground">{fieldLabel}:</span>
                  <div className="flex flex-wrap gap-1">
                    {values.slice(0, 5).map((item) => (
                      <button
                        key={item.value}
                        onClick={() => onHotValueClick?.(field, item.value)}
                        className={cn(
                          'px-1.5 py-0.5 rounded text-[10px] font-medium transition-opacity hover:opacity-80',
                          getFieldColor(field)
                        )}
                      >
                        {item.value}
                        <span className="text-[9px] opacity-70 ml-0.5">({item.count})</span>
                      </button>
                    ))}
                  </div>
                </div>
              )
            })}
          </CardContent>
        </Card>

        {/* Auto Evaluation */}
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              自动评测
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <div className="text-center p-2 bg-muted/50 rounded-lg">
                <div className="text-lg font-bold font-mono text-foreground">
                  {evaluation.precision.toFixed(1)}%
                </div>
                <div className="text-[10px] text-muted-foreground">Precision</div>
              </div>
              <div className="text-center p-2 bg-muted/50 rounded-lg">
                <div className="text-lg font-bold font-mono text-foreground">
                  {evaluation.recall.toFixed(1)}%
                </div>
                <div className="text-[10px] text-muted-foreground">Recall</div>
              </div>
              <div className="text-center p-2 bg-muted/50 rounded-lg">
                <div className="text-lg font-bold font-mono text-primary">
                  {evaluation.f1.toFixed(1)}%
                </div>
                <div className="text-[10px] text-muted-foreground">F1</div>
              </div>
            </div>

            <div className="pt-2 border-t border-border">
              <div className="text-[10px] text-muted-foreground mb-2">各字段 F1 分数</div>
              <div className="space-y-1">
                {evaluation.perFieldF1.map((item) => (
                  <div key={item.field} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{item.field}</span>
                    <span className={cn(
                      'font-mono font-medium',
                      item.f1 >= 60 ? 'text-green-600' : item.f1 >= 40 ? 'text-amber-600' : 'text-red-600'
                    )}>
                      {item.f1.toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Manual Judgments */}
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-primary" />
              人工评价
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-3">
            <div className="text-center p-3 bg-muted/50 rounded-lg">
              <div className="text-2xl font-bold font-mono text-foreground">
                {judgments.accuracy.toFixed(1)}%
              </div>
              <div className="text-xs text-muted-foreground">总体准确率</div>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="flex items-center justify-between p-2 bg-muted/30 rounded">
                <span className="text-muted-foreground">总评价数</span>
                <span className="font-medium">{judgments.total}</span>
              </div>
              <div className="flex items-center justify-between p-2 bg-green-50 rounded">
                <span className="text-green-700">准确</span>
                <span className="font-medium text-green-700">{judgments.correct}</span>
              </div>
              <div className="flex items-center justify-between p-2 bg-amber-50 rounded">
                <span className="text-amber-700">部分准确</span>
                <span className="font-medium text-amber-700">{judgments.partial}</span>
              </div>
              <div className="flex items-center justify-between p-2 bg-red-50 rounded">
                <span className="text-red-700">不准确</span>
                <span className="font-medium text-red-700">{judgments.incorrect}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  )
}
