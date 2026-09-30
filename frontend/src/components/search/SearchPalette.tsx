import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { api, type Schema } from "@/api/client";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { required } from "@/lib/httpError";

export function SearchPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [input, setInput] = useState("");
  const [debounced, setDebounced] = useState("");
  const q = input.trim();
  const navigate = useNavigate();
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(q), 200);
    return () => clearTimeout(timer);
  }, [q]);
  const ready = open && q.length >= 2 && q === debounced;
  const search = useQuery({
    queryKey: ["search", debounced], enabled: ready,
    queryFn: async ({ signal }) => {
      const { data, response } = await api.GET("/api/search", { params: { query: { q: debounced } }, signal });
      return required(data, response);
    },
  });
  function select(hit: Schema<"SearchHit">) {
    onOpenChange(false);
    navigate(`/${hit.kind}/${hit.kind === "company" ? hit.ticker || hit.cik : hit.cik}`);
  }
  const groups = [
    { label: "Companies", items: search.data?.companies ?? [] },
    { label: "Insiders", items: search.data?.insiders ?? [] },
    { label: "Funds", items: search.data?.funds ?? [] },
  ];
  return <CommandDialog open={open} onOpenChange={onOpenChange} title="Search profiles"
    description="Find companies, insiders and funds by name or ticker." shouldFilter={false}>
    <CommandInput aria-label="Search profiles" placeholder="Search companies, insiders, funds…" value={input} onValueChange={setInput} />
    <CommandList>
      {q.length < 2 ? <p className="p-4 text-sm text-muted-foreground">Type at least two characters</p> : !ready || search.isPending ?
        <p className="p-4 text-sm text-muted-foreground" role="status">Searching…</p> : search.isError ?
        <div className="p-4 text-sm"><p role="alert">Search didn't load. {search.error.message}</p>
          <button type="button" className="mt-2 text-link hover:underline" onClick={() => { void search.refetch(); }}>Try again</button></div> : <>
          <CommandEmpty>No matching profiles</CommandEmpty>
          {groups.filter((group) => group.items.length > 0).map((group) => <CommandGroup key={group.label} heading={group.label}>
            {group.items.map((hit) => <CommandItem key={`${hit.kind}:${hit.cik}`} value={`${hit.kind}:${hit.cik}`} onSelect={() => select(hit)}>
              <div className="min-w-0"><span className="block truncate">{hit.name}</span>{hit.subtitle && <span className="block truncate text-xs text-muted-foreground">{hit.subtitle}</span>}</div>
            </CommandItem>)}
          </CommandGroup>)}
        </>}
    </CommandList>
  </CommandDialog>;
}
