import React from 'react';
import { LifeBuoy } from 'lucide-react';
import { useT } from '../../i18n';

export default function GuideView() {
  const t = useT();
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="text-lg font-bold text-text mb-6 flex items-center gap-2"><LifeBuoy size={18} />{t('guide.title')}</h2>
      <div className="max-w-3xl flex flex-col gap-4">
        {[1, 2, 3, 4, 5, 6, 7].map((n) => (
          <div key={n} className="bg-surface-2 border border-surface-border rounded-xl p-4">
            <h3 className="text-sm font-semibold text-text mb-1">{t(`guide.s${n}.t`)}</h3>
            <p className="text-sm text-text-muted leading-relaxed">{t(`guide.s${n}.p`)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
