import React, { useState, useEffect } from 'react';
import { Quote } from 'lucide-react';

const QUOTES = [
    { text: "주식 시장은 적극적인 자에게서 참을성 있는 자에게로 돈이 넘어가도록 설계되어 있다.", author: "워런 버핏" },
    { text: "위험은 자신이 무엇을 하는지 모르는 데서 온다.", author: "워런 버핏" },
    { text: "가격은 당신이 지불하는 것이고, 가치는 당신이 얻는 것이다.", author: "워런 버핏" },
    { text: "단기적으로 시장은 투표기지만, 장기적으로는 저울이다.", author: "벤저민 그레이엄" },
    { text: "무엇을 소유하고 있는지 알고, 왜 소유하고 있는지 알아라.", author: "피터 린치" },
    { text: "투자에 있어 가장 위험한 네 단어는 '이번에는 다르다'이다.", author: "존 템플턴" },
    { text: "복리는 세계 8대 불가사의다.", author: "알베르트 아인슈타인" },
    { text: "남들이 욕심을 부릴 때 두려워하고, 남들이 두려워할 때 욕심을 부려라.", author: "워런 버핏" },
    { text: "투자는 IQ와 상관없다. 평범한 지능을 가진 사람도 감정을 통제할 수 있다면 위대한 투자자가 될 수 있다.", author: "워런 버핏" },
    { text: "10년 이상 보유할 생각이 없다면 단 10분도 보유하지 마라.", author: "워런 버핏" },
];

export const InvestmentQuote: React.FC<{ className?: string }> = ({ className = "" }) => {
    const [quote, setQuote] = useState(QUOTES[0]);

    useEffect(() => {
        const randomIndex = Math.floor(Math.random() * QUOTES.length);
        setQuote(QUOTES[randomIndex]);
    }, []);

    return (
        <div className={`flex flex-col ${className}`}>
            <div className="flex items-start gap-2">
                <Quote size={16} className="text-indigo-400 shrink-0 mt-1" />
                <div>
                    <p className="text-sm font-medium text-slate-800 leading-snug break-keep">
                        {quote.text}
                    </p>
                    <p className="text-xs text-slate-500 mt-1 text-right">
                        - {quote.author}
                    </p>
                </div>
            </div>
        </div>
    );
};
