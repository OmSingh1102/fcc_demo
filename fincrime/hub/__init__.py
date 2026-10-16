"""The engine under the console's file book (the reconciliation log): it
began as the Straive KYC Operations Hub, a second demo whose screens have
since been removed; the console draws its documents and reads names and
addresses with these modules.

Package map:
  loader / parse     the CSV becomes case records (every field parsed, nothing judged)
  names / addresses  rule tables for names and addresses (the AI Agent's checks use them)
  similarity         folding, Jaro-Winkler, phonetic keys
  documents          synthetic uploads: a deterministic defect plan and SVG rendering
  llm                the Straive LLM Foundry gateway the AI Agent calls Claude through
  agents/, pipeline  the hub's deterministic agents and their run over the book
                     (no longer used by a screen; kept with their tests)
"""
