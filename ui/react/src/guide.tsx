/* The getting-started guide: a dialog with a tinted header, numbered steps, a body and
   Back / Next at the foot. It opens by itself the first time the dashboard opens. */
import { useState, type ReactNode } from "react";
import { cls } from "./util.js";
import { Button } from "./controls.js";

export interface GuideContentProps {
  /** Each step's title. */
  steps?: string[];
  /** The current step's index. */
  step?: number;
  /** The small line over the title. Defaults to "Welcome to arbiter" or "Step 2 of 5". */
  kicker?: ReactNode;
  title?: ReactNode;
  tint?: "sage" | "peach" | "lilac" | "pink";
  /** The step's content. */
  body?: ReactNode;
  onStep?: (index: number) => void;
  onSkip?: () => void;
  onBack?: () => void;
  onNext?: () => void;
}

/** The parts that fill the guide dialog. */
export function GuideContent({ steps = [], step = 0, kicker, title, tint = "sage", body, onStep, onSkip, onBack, onNext }: GuideContentProps) {
  const last = step === steps.length - 1;
  return (
    <>
      <div className={`guide-head ${tint}`}>
        <div className="guide-steps">
          {steps.map((t, i) => (
            <button key={i} type="button" className={cls("step", i === step ? "on" : i < step ? "done" : "")} aria-label={t}
              onClick={onStep ? () => onStep(i) : undefined}>{String(i + 1)}</button>
          ))}
        </div>
        <div className="k">{kicker || (step === 0 ? "Welcome to arbiter" : `Step ${step + 1} of ${steps.length}`)}</div>
        <h2 id="guide-title">{title || steps[step] || ""}</h2>
      </div>
      <div className="guide-body">{body}</div>
      <div className="guide-foot">
        <Button label={last ? "Close" : "Skip the guide"} variant="link" onClick={onSkip} />
        <span className="spacer" />
        {step ? <Button label="Back" onClick={onBack} /> : null}
        <Button label={last ? "Done" : "Next"} variant="primary" onClick={onNext} />
      </div>
    </>
  );
}

export interface GuideProps extends GuideContentProps {
  /** Shows it in place. The dashboard opens it as a modal instead. */
  open?: boolean;
}

/** The guide dialog with its content. */
export function Guide({ open = false, ...props }: GuideProps) {
  return <dialog id="guide" open={open || undefined} aria-labelledby="guide-title"><GuideContent {...props} /></dialog>;
}

export interface GuideRowProps {
  name: ReactNode;
  detail?: ReactNode;
  /** Set the name in monospace, for probe serials. */
  mono?: boolean;
  /** A pill or button on the right. */
  end?: ReactNode;
}

/** A framed row in a guide list: a board or a probe, with a pill or button on the right. */
export function GuideRow({ name, detail, mono = false, end }: GuideRowProps) {
  return <div className="row"><b className={cls("name", mono && "mono")}>{name}</b>{detail ? <span className="mono muted">{detail}</span> : null}{end || null}</div>;
}

/** A list of GuideRows. */
export function GuideList({ rows = [] }: { rows?: GuideRowProps[] }) {
  return <div className="guide-list">{rows.map((r, i) => <GuideRow key={i} {...r} />)}</div>;
}

/** Health check counts as pills: OK, warnings, failed. */
export function Tally({ ok = 0, warn = 0, fail = 0 }: { ok?: number; warn?: number; fail?: number }) {
  return (
    <div className="tally">
      <span className="t ok"><b>{String(ok)}</b>{" OK"}</span>
      <span className={cls("t", !!warn && "warn")}><b>{String(warn)}</b>{" warnings"}</span>
      <span className={cls("t", !!fail && "err")}><b>{String(fail)}</b>{" failed"}</span>
    </div>
  );
}

/** A dark box with a command to paste, and a Copy button. */
export function CmdBox({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }, () => {});
  };
  return <div className="cmd-box"><pre>{text}</pre><Button label={copied ? "Copied" : "Copy"} size="small" onClick={copy} /></div>;
}

/** A numbered tip: a pink circled number, a bold title and a line under it. */
export function TourItem({ n, title, text }: { n: number; title: ReactNode; text: ReactNode }) {
  return <div className="tour-item"><span className="n">{String(n)}</span><div><b>{title}</b><div className="muted">{text}</div></div></div>;
}
