export const cn = (...classes: Array<string | false | null | undefined>) =>
    classes.filter(Boolean).join(' ');

export const ui = {
    card: 'bg-white rounded-2xl shadow-sm border border-slate-100',
    label: 'block text-sm font-medium text-slate-700 mb-2',
    input: 'w-full px-4 py-3 rounded-lg border border-slate-200 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-colors',
};
