// Mock data types for Skills IE
export interface Skill {
  id: string
  name: string
  category: string
  owner: string
  description: string
  detailUrl: string
  isExtracted: boolean
  extraction?: SkillExtraction
}

export interface SkillExtraction {
  platforms: ExtractionField
  languages: ExtractionField
  actionTypes: ExtractionField
  targetDomains: ExtractionField
  outputFormats: ExtractionField
  metrics: MetricField
  rawText: string
}

export interface ExtractionField {
  values: string[]
  evidence: string
  source: string
}

export interface MetricField {
  values: { value: string; unit: string }[]
  evidence: string
  source: string
}

export interface CoverageStats {
  field: string
  fieldLabel: string
  extracted: number
  total: number
  percentage: number
}

export interface HotValue {
  value: string
  count: number
}

export interface EvaluationMetrics {
  precision: number
  recall: number
  f1: number
  perFieldF1: { field: string; f1: number }[]
}

export interface ManualJudgment {
  total: number
  correct: number
  partial: number
  incorrect: number
  accuracy: number
}

// Mock data
export const mockSkills: Skill[] = [
  {
    id: '1',
    name: 'GitHub Issue Analyzer',
    category: '数据分析',
    owner: '张三',
    description: 'A comprehensive tool for analyzing GitHub issues with AI-powered insights and automated categorization capabilities.',
    detailUrl: 'https://example.com/skill/1',
    isExtracted: true,
    extraction: {
      platforms: { values: ['github', 'slack'], evidence: 'integrates with GitHub and Slack APIs for seamless workflow', source: 'gliner_direct' },
      languages: { values: ['python', 'typescript'], evidence: 'Built with Python backend and TypeScript frontend', source: 'llm_extraction' },
      actionTypes: { values: ['search', 'analyze', 'report'], evidence: 'can search issues, analyze patterns, and generate reports', source: 'gliner_direct' },
      targetDomains: { values: ['devops', 'project-management'], evidence: 'designed for DevOps teams and project management workflows', source: 'llm_extraction' },
      outputFormats: { values: ['json', 'csv', 'markdown'], evidence: 'exports data in JSON, CSV, and Markdown formats', source: 'gliner_direct' },
      metrics: { values: [{ value: '99.5', unit: '%' }, { value: '1000', unit: 'issues/min' }], evidence: 'achieves 99.5% accuracy processing 1000 issues per minute', source: 'llm_extraction' },
      rawText: 'GitHub Issue Analyzer is a comprehensive tool for analyzing GitHub issues with AI-powered insights. It integrates with GitHub and Slack APIs for seamless workflow. Built with Python backend and TypeScript frontend, it can search issues, analyze patterns, and generate reports. Designed for DevOps teams and project management workflows, it exports data in JSON, CSV, and Markdown formats. The tool achieves 99.5% accuracy processing 1000 issues per minute.'
    }
  },
  {
    id: '2',
    name: 'Slack Bot Builder',
    category: '自动化',
    owner: '李四',
    description: 'Create custom Slack bots with natural language processing capabilities for team communication automation.',
    detailUrl: 'https://example.com/skill/2',
    isExtracted: true,
    extraction: {
      platforms: { values: ['slack', 'notion'], evidence: 'works with Slack and syncs to Notion', source: 'gliner_direct' },
      languages: { values: ['javascript', 'node.js'], evidence: 'implemented in JavaScript running on Node.js', source: 'llm_extraction' },
      actionTypes: { values: ['create', 'automate', 'notify'], evidence: 'create bots, automate responses, and send notifications', source: 'gliner_direct' },
      targetDomains: { values: ['communication', 'productivity'], evidence: 'enhances team communication and productivity', source: 'llm_extraction' },
      outputFormats: { values: ['json'], evidence: 'outputs structured JSON responses', source: 'gliner_direct' },
      metrics: { values: [{ value: '500', unit: 'ms' }], evidence: 'average response time of 500ms', source: 'llm_extraction' },
      rawText: 'Slack Bot Builder enables creating custom Slack bots with NLP capabilities. It works with Slack and syncs to Notion, implemented in JavaScript running on Node.js. Users can create bots, automate responses, and send notifications. It enhances team communication and productivity, outputting structured JSON responses with an average response time of 500ms.'
    }
  },
  {
    id: '3',
    name: 'AWS Lambda Deployer',
    category: '云服务',
    owner: '王五',
    description: 'Streamlined deployment tool for AWS Lambda functions with automated testing and monitoring.',
    detailUrl: 'https://example.com/skill/3',
    isExtracted: true,
    extraction: {
      platforms: { values: ['aws', 'github'], evidence: 'deploys to AWS with GitHub integration', source: 'gliner_direct' },
      languages: { values: ['python', 'go', 'rust'], evidence: 'supports Python, Go, and Rust runtimes', source: 'llm_extraction' },
      actionTypes: { values: ['deploy', 'test', 'monitor'], evidence: 'handles deployment, testing, and monitoring', source: 'gliner_direct' },
      targetDomains: { values: ['serverless', 'cloud-computing'], evidence: 'optimized for serverless and cloud computing', source: 'llm_extraction' },
      outputFormats: { values: ['yaml', 'json', 'cloudformation'], evidence: 'generates YAML, JSON, and CloudFormation templates', source: 'gliner_direct' },
      metrics: { values: [{ value: '30', unit: 'sec' }, { value: '99.9', unit: '%' }], evidence: 'deploys in 30 seconds with 99.9% success rate', source: 'llm_extraction' },
      rawText: 'AWS Lambda Deployer streamlines deployment of Lambda functions. It deploys to AWS with GitHub integration, supporting Python, Go, and Rust runtimes. The tool handles deployment, testing, and monitoring, optimized for serverless and cloud computing. It generates YAML, JSON, and CloudFormation templates, deploying in 30 seconds with 99.9% success rate.'
    }
  },
  {
    id: '4',
    name: 'SEO Keyword Extractor',
    category: 'SEO',
    owner: '赵六',
    description: 'Extract and analyze keywords from web content for SEO optimization with competitive analysis.',
    detailUrl: 'https://example.com/skill/4',
    isExtracted: false,
  },
  {
    id: '5',
    name: 'Database Migration Tool',
    category: '数据库',
    owner: '钱七',
    description: 'Automated database schema migration with rollback support and data validation.',
    detailUrl: 'https://example.com/skill/5',
    isExtracted: true,
    extraction: {
      platforms: { values: ['postgresql', 'mysql', 'mongodb'], evidence: 'supports PostgreSQL, MySQL, and MongoDB', source: 'gliner_direct' },
      languages: { values: ['sql', 'python'], evidence: 'uses SQL and Python scripts', source: 'llm_extraction' },
      actionTypes: { values: ['migrate', 'validate', 'rollback'], evidence: 'performs migrations, validations, and rollbacks', source: 'gliner_direct' },
      targetDomains: { values: ['database-management', 'backend'], evidence: 'for database management and backend systems', source: 'llm_extraction' },
      outputFormats: { values: ['sql', 'json'], evidence: 'outputs SQL scripts and JSON logs', source: 'gliner_direct' },
      metrics: { values: [{ value: '1M', unit: 'rows/min' }], evidence: 'processes 1 million rows per minute', source: 'llm_extraction' },
      rawText: 'Database Migration Tool automates schema migrations with rollback support. It supports PostgreSQL, MySQL, and MongoDB, using SQL and Python scripts. The tool performs migrations, validations, and rollbacks for database management and backend systems. It outputs SQL scripts and JSON logs, processing 1 million rows per minute.'
    }
  },
  {
    id: '6',
    name: 'API Documentation Generator',
    category: '文档',
    owner: '孙八',
    description: 'Automatically generate comprehensive API documentation from source code with examples.',
    detailUrl: 'https://example.com/skill/6',
    isExtracted: true,
    extraction: {
      platforms: { values: ['github', 'gitlab'], evidence: 'integrates with GitHub and GitLab repositories', source: 'gliner_direct' },
      languages: { values: ['javascript', 'python', 'java'], evidence: 'parses JavaScript, Python, and Java codebases', source: 'llm_extraction' },
      actionTypes: { values: ['generate', 'analyze', 'publish'], evidence: 'generates, analyzes, and publishes documentation', source: 'gliner_direct' },
      targetDomains: { values: ['api-development', 'documentation'], evidence: 'designed for API development and documentation', source: 'llm_extraction' },
      outputFormats: { values: ['html', 'markdown', 'openapi'], evidence: 'produces HTML, Markdown, and OpenAPI specs', source: 'gliner_direct' },
      metrics: { values: [{ value: '100', unit: 'endpoints/sec' }], evidence: 'documents 100 endpoints per second', source: 'llm_extraction' },
      rawText: 'API Documentation Generator automatically creates comprehensive API docs. It integrates with GitHub and GitLab repositories, parsing JavaScript, Python, and Java codebases. The tool generates, analyzes, and publishes documentation for API development. It produces HTML, Markdown, and OpenAPI specs, documenting 100 endpoints per second.'
    }
  },
  {
    id: '7',
    name: 'Image Optimizer Pro',
    category: '媒体处理',
    owner: '周九',
    description: 'Batch image optimization with smart compression algorithms and format conversion.',
    detailUrl: 'https://example.com/skill/7',
    isExtracted: true,
    extraction: {
      platforms: { values: ['aws-s3', 'cloudinary'], evidence: 'works with AWS S3 and Cloudinary storage', source: 'gliner_direct' },
      languages: { values: ['rust', 'webassembly'], evidence: 'built with Rust and WebAssembly for performance', source: 'llm_extraction' },
      actionTypes: { values: ['compress', 'convert', 'resize'], evidence: 'compresses, converts, and resizes images', source: 'gliner_direct' },
      targetDomains: { values: ['web-performance', 'media'], evidence: 'improves web performance and media handling', source: 'llm_extraction' },
      outputFormats: { values: ['webp', 'avif', 'jpeg'], evidence: 'outputs WebP, AVIF, and optimized JPEG', source: 'gliner_direct' },
      metrics: { values: [{ value: '70', unit: '%' }, { value: '50', unit: 'img/sec' }], evidence: 'achieves 70% size reduction at 50 images per second', source: 'llm_extraction' },
      rawText: 'Image Optimizer Pro provides batch image optimization with smart compression. It works with AWS S3 and Cloudinary storage, built with Rust and WebAssembly for performance. The tool compresses, converts, and resizes images to improve web performance and media handling. It outputs WebP, AVIF, and optimized JPEG, achieving 70% size reduction at 50 images per second.'
    }
  },
  {
    id: '8',
    name: 'Log Aggregator',
    category: '监控',
    owner: '吴十',
    description: 'Centralized log collection and analysis with real-time alerting and dashboards.',
    detailUrl: 'https://example.com/skill/8',
    isExtracted: false,
  },
  {
    id: '9',
    name: 'CI/CD Pipeline Manager',
    category: 'DevOps',
    owner: '郑十一',
    description: 'Visual pipeline builder for CI/CD workflows with multi-cloud deployment support.',
    detailUrl: 'https://example.com/skill/9',
    isExtracted: true,
    extraction: {
      platforms: { values: ['github-actions', 'jenkins', 'gitlab-ci'], evidence: 'supports GitHub Actions, Jenkins, and GitLab CI', source: 'gliner_direct' },
      languages: { values: ['yaml', 'groovy', 'bash'], evidence: 'uses YAML, Groovy, and Bash configurations', source: 'llm_extraction' },
      actionTypes: { values: ['build', 'test', 'deploy'], evidence: 'manages build, test, and deploy stages', source: 'gliner_direct' },
      targetDomains: { values: ['devops', 'automation'], evidence: 'streamlines DevOps and automation workflows', source: 'llm_extraction' },
      outputFormats: { values: ['yaml', 'json', 'xml'], evidence: 'generates YAML, JSON, and XML configs', source: 'gliner_direct' },
      metrics: { values: [{ value: '5', unit: 'min' }, { value: '95', unit: '%' }], evidence: 'average pipeline time 5 minutes with 95% success rate', source: 'llm_extraction' },
      rawText: 'CI/CD Pipeline Manager provides visual pipeline building for CI/CD workflows. It supports GitHub Actions, Jenkins, and GitLab CI, using YAML, Groovy, and Bash configurations. The tool manages build, test, and deploy stages, streamlining DevOps and automation workflows. It generates YAML, JSON, and XML configs with average pipeline time of 5 minutes and 95% success rate.'
    }
  },
  {
    id: '10',
    name: 'Security Scanner',
    category: '安全',
    owner: '王十二',
    description: 'Automated security vulnerability scanning for web applications and APIs.',
    detailUrl: 'https://example.com/skill/10',
    isExtracted: true,
    extraction: {
      platforms: { values: ['github', 'docker'], evidence: 'scans GitHub repos and Docker images', source: 'gliner_direct' },
      languages: { values: ['python', 'javascript'], evidence: 'analyzes Python and JavaScript code', source: 'llm_extraction' },
      actionTypes: { values: ['scan', 'report', 'remediate'], evidence: 'scans, reports, and suggests remediation', source: 'gliner_direct' },
      targetDomains: { values: ['security', 'compliance'], evidence: 'ensures security and compliance standards', source: 'llm_extraction' },
      outputFormats: { values: ['sarif', 'json', 'pdf'], evidence: 'outputs SARIF, JSON, and PDF reports', source: 'gliner_direct' },
      metrics: { values: [{ value: '98', unit: '%' }, { value: '10K', unit: 'files/min' }], evidence: '98% detection rate scanning 10K files per minute', source: 'llm_extraction' },
      rawText: 'Security Scanner automates vulnerability scanning for web applications. It scans GitHub repos and Docker images, analyzing Python and JavaScript code. The tool scans, reports, and suggests remediation to ensure security and compliance standards. It outputs SARIF, JSON, and PDF reports with 98% detection rate scanning 10K files per minute.'
    }
  },
]

// Generate more mock data with deterministic isExtracted values
for (let i = 11; i <= 50; i++) {
  const categories = ['数据分析', '自动化', '云服务', 'SEO', '数据库', '文档', '媒体处理', '监控', 'DevOps', '安全']
  const owners = ['张三', '李四', '王五', '赵六', '钱七', '孙八', '周九', '吴十', '郑十一', '王十二']
  // Use deterministic pattern based on index instead of Math.random()
  const isExtracted = i % 3 !== 0 // Every 3rd item is not extracted
  mockSkills.push({
    id: String(i),
    name: `技能工具 ${i}`,
    category: categories[i % categories.length],
    owner: owners[i % owners.length],
    description: `这是第 ${i} 个技能工具的描述，用于演示列表展示效果。`,
    detailUrl: `https://example.com/skill/${i}`,
    isExtracted,
  })
}

export const mockCoverageStats: CoverageStats[] = [
  { field: 'platforms', fieldLabel: '平台', extracted: 783, total: 1000, percentage: 78.3 },
  { field: 'languages', fieldLabel: '语言', extracted: 892, total: 1000, percentage: 89.2 },
  { field: 'actionTypes', fieldLabel: '操作类型', extracted: 654, total: 1000, percentage: 65.4 },
  { field: 'targetDomains', fieldLabel: '目标领域', extracted: 421, total: 1000, percentage: 42.1 },
  { field: 'outputFormats', fieldLabel: '输出格式', extracted: 567, total: 1000, percentage: 56.7 },
  { field: 'metrics', fieldLabel: '指标', extracted: 234, total: 1000, percentage: 23.4 },
]

export const mockHotValues: Record<string, HotValue[]> = {
  platforms: [
    { value: 'github', count: 342 },
    { value: 'slack', count: 198 },
    { value: 'aws', count: 156 },
    { value: 'notion', count: 89 },
    { value: 'docker', count: 76 },
  ],
  languages: [
    { value: 'python', count: 412 },
    { value: 'javascript', count: 287 },
    { value: 'typescript', count: 203 },
    { value: 'go', count: 134 },
    { value: 'rust', count: 98 },
  ],
  actionTypes: [
    { value: 'analyze', count: 356 },
    { value: 'deploy', count: 289 },
    { value: 'generate', count: 234 },
    { value: 'monitor', count: 187 },
    { value: 'automate', count: 156 },
  ],
}

export const mockEvaluation: EvaluationMetrics = {
  precision: 59.8,
  recall: 51.1,
  f1: 55.1,
  perFieldF1: [
    { field: '平台', f1: 72.3 },
    { field: '语言', f1: 81.5 },
    { field: '操作类型', f1: 54.2 },
    { field: '目标领域', f1: 38.7 },
    { field: '输出格式', f1: 62.1 },
    { field: '指标', f1: 21.8 },
  ]
}

export const mockJudgments: ManualJudgment = {
  total: 156,
  correct: 89,
  partial: 42,
  incorrect: 25,
  accuracy: 57.1
}
