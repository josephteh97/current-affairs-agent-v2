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