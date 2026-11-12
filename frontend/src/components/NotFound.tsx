/** 404：地址解析不出页面时，在应用外壳里显示（§3） */
import { FileQuestion } from 'lucide-react'
import { EmptyState } from '@/components/common/EmptyState'
import { Button } from '@/components/ui/button'
import { useI18n } from '@/i18n/core'

export function NotFound({ onHome }: { onHome: () => void }) {
  const { t } = useI18n()
  return (
    <div data-testid="not-found">
      <EmptyState icon={<FileQuestion className="size-6" />}
                  title={t('route.notFound.title')} hint={t('route.notFound.body')}
                  action={<Button variant="outline" onClick={onHome}>{t('route.notFound.back')}</Button>} />
    </div>
  )
}
