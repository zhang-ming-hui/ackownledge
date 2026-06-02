'use client'

import { useState } from 'react'
import { Database, Menu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
import { SkillBrowser } from '@/components/skill-browser'
import { SkillDetail } from '@/components/skill-detail'
import { StatsDashboard } from '@/components/stats-dashboard'
import {
  mockSkills,
  mockCoverageStats,
  mockHotValues,
  mockEvaluation,
  mockJudgments,
  type Skill,
} from '@/lib/mock-data'

export default function SkillsIEPage() {
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null)
  const [filterValue, setFilterValue] = useState('')
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)

  const handleSelectSkill = (skill: Skill) => {
    setSelectedSkill(skill)
    setIsMobileMenuOpen(false)
  }

  const handleHotValueClick = (field: string, value: string) => {
    setFilterValue(value)
  }

  const handleFilterChange = (value: string) => {
    setFilterValue(value)
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#e0e7ff] via-[#f0f4f8] to-[#ecfdf5]">
      {/* Header */}
      <header className="sticky top-0 z-50 bg-card/80 backdrop-blur-sm border-b border-border">
        <div className="flex items-center justify-between px-4 py-3 lg:px-6">
          <div className="flex items-center gap-3">
            {/* Mobile menu button */}
            <Sheet open={isMobileMenuOpen} onOpenChange={setIsMobileMenuOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="lg:hidden">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-[300px] p-0">
                <div className="h-full pt-12">
                  <SkillBrowser
                    skills={mockSkills}
                    selectedSkillId={selectedSkill?.id ?? null}
                    onSelectSkill={handleSelectSkill}
                    filterValue={filterValue}
                    onFilterChange={handleFilterChange}
                  />
                </div>
              </SheetContent>
            </Sheet>
            
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
                <Database className="h-4 w-4 text-primary-foreground" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-foreground">Skills IE</h1>
                <p className="text-[10px] text-muted-foreground hidden sm:block">信息抽取系统</p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground hidden sm:block">
              共 {mockSkills.length} 个技能
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex h-[calc(100vh-57px)]">
        {/* Left Panel - Skill Browser (Desktop) */}
        <aside className="hidden lg:block w-[280px] shrink-0 p-4 pr-2">
          <div className="h-full">
            <SkillBrowser
              skills={mockSkills}
              selectedSkillId={selectedSkill?.id ?? null}
              onSelectSkill={handleSelectSkill}
              filterValue={filterValue}
              onFilterChange={handleFilterChange}
            />
          </div>
        </aside>

        {/* Center Panel - Skill Detail */}
        <section className="flex-1 p-4 lg:px-2 min-w-0">
          <div className="h-full">
            <SkillDetail skill={selectedSkill} />
          </div>
        </section>

        {/* Right Panel - Stats Dashboard (Desktop) */}
        <aside className="hidden xl:block w-[340px] shrink-0 p-4 pl-2">
          <div className="h-full bg-card rounded-xl shadow-sm border border-border">
            <StatsDashboard
              coverageStats={mockCoverageStats}
              hotValues={mockHotValues}
              evaluation={mockEvaluation}
              judgments={mockJudgments}
              onHotValueClick={handleHotValueClick}
            />
          </div>
        </aside>
      </main>

      {/* Mobile Stats Toggle */}
      <div className="xl:hidden fixed bottom-4 right-4">
        <Sheet>
          <SheetTrigger asChild>
            <Button size="lg" className="rounded-full shadow-lg">
              <span className="mr-2">📊</span>
              统计
            </Button>
          </SheetTrigger>
          <SheetContent side="right" className="w-[340px] p-0">
            <div className="h-full pt-12">
              <StatsDashboard
                coverageStats={mockCoverageStats}
                hotValues={mockHotValues}
                evaluation={mockEvaluation}
                judgments={mockJudgments}
                onHotValueClick={handleHotValueClick}
              />
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </div>
  )
}
