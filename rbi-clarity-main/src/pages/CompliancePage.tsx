import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ShieldCheck, ShieldAlert, ShieldQuestion, Loader2, AlertTriangle, CheckCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { checkCompliance, getTopics, type ComplianceResult, FOLDER_SUBTOPICS } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import ReactMarkdown from "react-markdown";

const formatLabel = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const CompliancePage = () => {
  const [inputData, setInputData] = useState("");
  const [topic, setTopic] = useState<string>("all");
  const [entityType, setEntityType] = useState("");
  const [result, setResult] = useState<ComplianceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [topics, setTopics] = useState<string[]>(Object.keys(FOLDER_SUBTOPICS));
  const { toast } = useToast();

  useEffect(() => {
    getTopics()
      .then((data) => {
        if (data.topics?.length) {
          setTopics(data.topics.map((t) => t.topic_id));
        }
      })
      .catch(() => {});
  }, []);

  const handleCheck = async () => {
    if (!inputData.trim()) {
      toast({ title: "Missing data", description: "Please enter compliance data to check.", variant: "destructive" });
      return;
    }

    setLoading(true);
    setResult(null);
    try {
      const res = await checkCompliance({
        data: inputData,
        topic: topic !== "all" ? topic : undefined,
        entity_type: entityType || undefined,
      });
      setResult(res);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || "Failed to check compliance.";
      toast({ title: "Error", description: msg, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  const statusIcon = {
    COMPLIANT: <ShieldCheck className="h-8 w-8 text-green-600" />,
    NON_COMPLIANT: <ShieldAlert className="h-8 w-8 text-destructive" />,
    INSUFFICIENT_DATA: <ShieldQuestion className="h-8 w-8 text-yellow-600" />,
  };

  const statusColor = {
    COMPLIANT: "border-green-500/30 bg-green-50",
    NON_COMPLIANT: "border-destructive/30 bg-red-50",
    INSUFFICIENT_DATA: "border-yellow-500/30 bg-yellow-50",
  };

  return (
    <div className="p-6 md:p-10 max-w-3xl mx-auto">
      <h1 className="font-display text-2xl font-bold text-foreground mb-2">Compliance Checker</h1>
      <p className="text-muted-foreground mb-8">Check transaction data against RBI regulatory rules.</p>

      <Card className="p-6 space-y-5">
        <div className="space-y-2">
          <Label>Compliance Data</Label>
          <Textarea
            value={inputData}
            onChange={(e) => setInputData(e.target.value)}
            placeholder={`Enter as JSON or key: value format, e.g.:\naccount_type: savings\ntransaction_amount: 500000\nkyc_status: full_kyc`}
            className="min-h-[120px] font-mono text-sm"
          />
          <p className="text-xs text-muted-foreground">Accepts JSON or "field: value" format (one per line)</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Topic (optional)</Label>
            <Select value={topic} onValueChange={setTopic}>
              <SelectTrigger><SelectValue placeholder="All topics" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Topics</SelectItem>
                {topics.map((t) => (
                  <SelectItem key={t} value={t}>{formatLabel(t)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Entity Type (optional)</Label>
            <Select value={entityType || "none"} onValueChange={(v) => setEntityType(v === "none" ? "" : v)}>
              <SelectTrigger><SelectValue placeholder="Any entity" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Any Entity</SelectItem>
                <SelectItem value="commercial_banks">Commercial Banks</SelectItem>
                <SelectItem value="NBFC">NBFC</SelectItem>
                <SelectItem value="payment_banks">Payment Banks</SelectItem>
                <SelectItem value="Urban_Cooperative_Bank">Urban Cooperative Bank</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <Button onClick={handleCheck} disabled={loading} className="w-full">
          {loading ? <><Loader2 className="h-4 w-4 animate-spin mr-2" /> Checking...</> : "Check Compliance"}
        </Button>
      </Card>

      {result && (
        <div className="mt-6 space-y-4">
          {/* Status card */}
          <Card className={`p-6 border-2 ${statusColor[result.overall_status]}`}>
            <div className="flex items-center gap-3 mb-4">
              {statusIcon[result.overall_status]}
              <div>
                <h3 className="font-semibold text-lg text-foreground">
                  {result.overall_status === "COMPLIANT" ? "Compliant" :
                   result.overall_status === "NON_COMPLIANT" ? "Non-Compliant" :
                   "Insufficient Data"}
                </h3>
                <p className="text-sm text-muted-foreground">
                  {result.rules_evaluated} rules evaluated · {result.violations_count} violations · {result.passed_count} passed
                </p>
              </div>
            </div>

            {/* AI Summary */}
            {result.summary && (
              <div className="bg-background/50 rounded-lg p-4 mb-4">
                <h4 className="text-sm font-medium text-foreground mb-2">Summary</h4>
                <div className="text-sm text-muted-foreground prose prose-sm max-w-none">
                  <ReactMarkdown>{result.summary}</ReactMarkdown>
                </div>
              </div>
            )}
          </Card>

          {/* Violations */}
          {result.violations.length > 0 && (
            <Card className="p-5">
              <h4 className="font-medium text-foreground mb-3 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-destructive" />
                Violations ({result.violations.length})
              </h4>
              <div className="space-y-3">
                {result.violations.map((v, i) => (
                  <div key={i} className="border-l-2 border-destructive pl-3">
                    <p className="text-sm font-medium text-foreground">{v.title}</p>
                    <p className="text-xs text-muted-foreground mb-1">Rule: {v.rule_id} · {formatLabel(v.topic)}/{formatLabel(v.subtopic)}</p>
                    {v.violations.map((desc, j) => (
                      <p key={j} className="text-sm text-destructive">{desc}</p>
                    ))}
                    {v.source && <Badge variant="outline" className="text-xs mt-1">Source: {v.source}</Badge>}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Passed */}
          {result.passed.length > 0 && (
            <Card className="p-5">
              <h4 className="font-medium text-foreground mb-3 flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-green-600" />
                Passed ({result.passed.length})
              </h4>
              <div className="space-y-2">
                {result.passed.map((p, i) => (
                  <div key={i} className="border-l-2 border-green-500 pl-3">
                    <p className="text-sm font-medium text-foreground">{p.title}</p>
                    <p className="text-xs text-muted-foreground">Rule: {p.rule_id}</p>
                    {p.passed.map((desc, j) => (
                      <p key={j} className="text-sm text-green-700">{desc}</p>
                    ))}
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
};

export default CompliancePage;
