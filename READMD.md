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


  flowchart TB                                                                                                                                                                                                   
      %% ── Entry Points ──────────────────────────────────────────────                                                                                                                                          
      CLI["👤 CLI User\n(terminal)"]                                                                                                                                                                             
      MCP_CLIENT["🖥️  MCP Client\n(Claude Desktop, etc.)"]                                                                                                                                                        
                                                                                                                                                                                                                 
      %% ── Two Runtime Paths ─────────────────────────────────────────                                                                                                                                          
      subgraph AGENT["agent.py  —  Standalone ReAct Agent"]                                                                                                                                                      
          direction TB                                                                                                                                                                                           
          A1["Intent Detection\nis_essay_request()\nneeds_live_search()"]                                                                                                                                        
          A2["Forced web_search\n(current-events bypass)"]                                                                                                                                                       
          A3["build_system_prompt()\nskills + memory + rules"]                                                                                                                                                   
          A4["Ollama LLM\nllama3.1:8b  /  localhost:11434"]                                                                                                                                                      
          A5["ReAct Parser\nTHOUGHT → ACTION → OBSERVATION"]                                                                                                                                                     
          A6["evaluate_turn()\nabsorb_lessons()"]                                                                                                                                                                
          A1 --> A2 --> A3 --> A4                                                                                                                                                                                
          A4 --> A5 --> A4                                                                                                                                                                                       
          A5 --> A6                                                                                                                                                                                              
      end                                                                                                                                                                                                      
                                                                                                                                                                                                                 
      subgraph MCP["mcp_agent_server.py  —  MCP Tool Server"]                                                                                                                                                    
          direction TB
          M1["FastMCP\nmcp.tool() registration"]                                                                                                                                                                 
          M2["remember_context()\nMCP-only key-value store\n(memory.md)"]                                                                                                                                        
          M1 --- M2                                                                                                                                                                                              
      end                                                                                                                                                                                                        
                                                                                                                                                                                                                 
      %% ── Shared Tool Layer ─────────────────────────────────────────                                                                                                                                          
      subgraph TOOLS["tools.py  —  Single Source of Truth"]                                                                                                                                                    
          direction LR                                                                                                                                                                                           
          T1["web_search()\nDDGS.news() → .text() fallback"]
          T2["web_fetch()\nHTML strip, 8 000 char cap"]                                                                                                                                                          
          T3["write_essay()\nthink-tank scaffold"]                                                                                                                                                               
          T4["rate_source()\nget_best_sources()"]                                                                                                                                                                
          T5["log_writing_feedback()\nrecall_writing_feedback()"]                                                                                                                                                
      end                                                                                                                                                                                                        
                                                                                                                                                                                                               
      %% ── Skills (Prompt Context) ───────────────────────────────────                                                                                                                                          
      subgraph SKILLS["skills/  —  Loaded into System Prompt"]                                                                                                                                                 
          direction TB                                                                                                                                                                                           
          S1["news_search.md\nalways loaded"]                                                                                                                                                                  
          S2["self_learning.md\nalways loaded"]                                                                                                                                                                  
          S3["essay_writing.md\nessay_mode only"]
      end                                                                                                                                                                                                        
                  
      %% ── External Services ─────────────────────────────────────────                                                                                                                                          
      DDG["🌐 DuckDuckGo\nSearch API"]
      WEB["🌐 External URLs\n(Reuters, BBC, WSJ…)"]                                                                                                                                                              
                                                                                                                                                                                                                 
      %% ── Persistence ───────────────────────────────────────────────                                                                                                                                          
      subgraph MEMORY["Persistence"]                                                                                                                                                                             
          direction TB                                                                                                                                                                                           
          DB[("agent_memory.db\nSQLite\n─────────────\nsource_quality\nwriting_feedback")]
          JSON[("agent_memory.json\nRL Heuristic\n─────────────\nlearned_rules\nstats / episodes")]                                                                                                              
      end                                                                                                                                                                                                        
                                                                                                                                                                                                                 
      %% ── Connections ───────────────────────────────────────────────                                                                                                                                          
      CLI      --> AGENT
      MCP_CLIENT --> MCP                                                                                                                                                                                         
                  
      AGENT   -->|"imports"| TOOLS                                                                                                                                                                               
      MCP     -->|"imports"| TOOLS
                                                                                                                                                                                                                 
      AGENT   -->|"reads on startup\n& each turn"| SKILLS                                                                                                                                                        
      AGENT   -->|"load_memory()\nsave_memory()"| JSON
                                                                                                                                                                                                                 
      T1      --> DDG                                                                                                                                                                                            
      T2      --> WEB
      T4      --> DB                                                                                                                                                                                             
      T5      --> DB



  ┌─────────────┬─────────────────────────────────────┬──────────────────────────────────────────────────────────────────┐
  │    Layer    │                Files                │                               Role                               │                                                                                       
  ├─────────────┼─────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
  │ Entry       │ CLI / MCP Client                    │ Two ways to reach the system                                     │                                                                                       
  ├─────────────┼─────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
  │ Agents      │ agent.py / mcp_agent_server.py      │ Runtime logic — import tools, never redefine them                │                                                                                       
  ├─────────────┼─────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤                                                                                       
  │ Tools       │ tools.py                            │ Single source of truth — fix once, both agents benefit           │                                                                                       
  ├─────────────┼─────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤                                                                                       
  │ Skills      │ skills/*.md                         │ Prompt-injected playbooks; essay_writing.md loaded conditionally │
  ├─────────────┼─────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤                                                                                       
  │ Persistence │ agent_memory.db + agent_memory.json │ SQLite for source/writing quality; JSON for RL heuristic rules   │
  ├─────────────┼─────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤                                                                                       
  │ External    │ DuckDuckGo + web URLs               │ Live data; never baked into the model                            │
  └─────────────┴─────────────────────────────────────┴──────────────────────────────────────────────────────────────────┘    