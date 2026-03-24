On file organization:                                                                                                                                                                                          
                                                                                                                                                                                                                 
  Since news research → essay writing is a single pipeline (you always research first, then write), splitting them into separate folders would create friction. A skills/ subfolder with separate files per      
  capability is the cleanest approach:                                                                                                                                                                           
                                                                                                                                                                                                                 
  current-affairs-agent-v2/
    skills/
      news_search.md       ← current skill.md moved here
      essay_writing.md     ← new think-tank essay skill                                                                                                                                                          
    mcp.py                 ← keep one MCP server at root (tools are interdependent)
    agent.py                                                                                                                                                                                                     
                  
  Split MCP files into folders only when they serve genuinely different agents/purposes. Right now web_search feeds write_essay — they belong together.   

  Structure decision — why one skills/ folder, not skill-per-folder:                                                                                                                                             
  The two skills are a sequential pipeline: research always feeds the essay. Pairing each skill with its own MCP subfolder would force the agent to stitch together tools from different places for no benefit.  
  If you later build a completely unrelated agent (e.g. a finance tracker or a translation agent), that's when a second top-level folder with its own mcp.py + skills/ makes sense.  


  What was added to mcp.py — 4 new tools:                                                                                                                                                                      
                                                                                                                                                                                                                 
  ┌──────────────────────────────────────────────────────┬──────────────────────────────────────────────────────────────────────────┐                                                                            
  │                         Tool                         │                                   Role                                   │                                                                            
  ├──────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤                                                                          
  │ rate_source(name, score, reason, topic_tag)          │ Write one quality rating after reading a source                          │
  ├──────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤
  │ get_best_sources(topic_tag, limit)                   │ Read ranked source table at session start — tells the agent who to trust │                                                                            
  ├──────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤                                                                            
  │ log_writing_feedback(component, feedback, sentiment) │ Write one lesson after finishing an essay section                        │                                                                            
  ├──────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────┤                                                                            
  │ recall_writing_feedback(component)                   │ Read past lessons before writing a section                               │                                                                          
  └──────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────┘                                                                            
                                                                                                                                                                                                               
  How the self-learning loop actually works:                                                                                                                                                                     
   
  Session 1: BBC scores 2/5 ("wire re-post, thin on detail") → stored                                                                                                                                            
  Session 2: get_best_sources() returns BBC near the bottom → agent skips it                                                                                                                                     
             Straits Times scores 5/5 twice → rises to top of geopolitics ranking                                                                                                                                
                                                                                                                                                                                                                 
  Session 1: "Conclusion was shallow" → logged as negative                                                                                                                                                       
  Session 2: recall_writing_feedback("conclusion") surfaces the note                                                                                                                                             
             Agent writes a forward-looking provocation instead → better essay                                                                                                                                   
             → logs it as positive → pattern reinforces                                                                                                                                                          
                                                                                                                                                                                                                 
  Why SQLite and not memory.md:                                                                                                                                                                                  
  - memory.md can't aggregate — you can't ask it "what is Reuters' average score after 20 uses?"                                                                                                                 
  - SQLite gives you AVG(), COUNT(), ordering, filtering by topic — all in stdlib, zero new dependencies                                                                                                         
  - All data is in one file (agent_memory.db) that persists and grows with every session                
                                                                                                                                                                                                                 
  Future path to vector search: self_learning.md documents exactly how to upgrade — the schema already has content_snippet which is what you'd embed. No migration needed, just add ChromaDB and point it at the 
  existing rows.                                                                                              