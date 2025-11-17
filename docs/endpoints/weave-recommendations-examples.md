# Weave Recommendations - Code Examples

## Python Integration Example

```python
import asyncio
import httpx
from typing import Optional
from uuid import uuid4

class WeaveClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"}
        )
    
    async def get_weave_recommendation(
        self,
        session_id: str,
        message_id: str,
        query: str,
        max_polls: int = 2,
        poll_interval_ms: int = 150
    ) -> Optional[dict]:
        """
        Get Weave recommendation with optional polling.
        
        Returns completed recommendation or None if not ready.
        """
        url = f"{self.base_url}/v1/weave/recommendations"
        payload = {
            "session_id": session_id,
            "message_id": message_id,
            "query": query
        }
        
        for attempt in range(max_polls + 1):
            try:
                response = await self.client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                
                if data["status"] == "completed":
                    return data
                elif data["status"] == "in_progress":
                    if attempt < max_polls:
                        # Poll again after suggested interval
                        retry_after_ms = data.get("retry_after_ms", poll_interval_ms)
                        await asyncio.sleep(retry_after_ms / 1000)
                        continue
                    else:
                        # Max polls reached, return None
                        return None
                elif data["status"] == "failed":
                    print(f"Weave auction failed: {data.get('error')}")
                    return None
            except Exception as e:
                print(f"Error fetching Weave recommendation: {e}")
                return None
        
        return None

# Usage in LLM handler
async def handle_user_message(session_id: str, user_query: str):
    message_id = f"msg_{uuid4()}"
    
    # Try to get Weave recommendation
    weave_client = WeaveClient("https://aip-server.example.com", "your-api-key")
    weave_rec = await weave_client.get_weave_recommendation(
        session_id=session_id,
        message_id=message_id,
        query=user_query
    )
    
    # Build LLM prompt
    llm_prompt = f"User query: {user_query}\n\n"
    
    if weave_rec:
        # Weave content available - add to prompt
        llm_prompt += f"Sponsored content: {weave_rec['weave_content']}\n\n"
    
    # Generate LLM response
    llm_response = await llm.generate(llm_prompt)
    
    # Return to user (aip-ui-sdk handles rendering)
    return llm_response
```

## JavaScript/TypeScript Integration Example

```typescript
interface WeaveRecommendation {
  status: 'completed' | 'in_progress' | 'failed';
  weave_content?: string;
  serve_token?: string;
  creative_metadata?: {
    brand_name: string;
    product_name: string;
    description: string;
    url: string;
  };
  retry_after_ms?: number;
  message?: string;
  error?: string;
}

class WeaveClient {
  constructor(
    private baseUrl: string,
    private apiKey: string
  ) {}

  async getWeaveRecommendation(
    sessionId: string,
    messageId: string,
    query: string,
    maxPolls: number = 2,
    pollIntervalMs: number = 150
  ): Promise<WeaveRecommendation | null> {
    const url = `${this.baseUrl}/v1/weave/recommendations`;
    const payload = {
      session_id: sessionId,
      message_id: messageId,
      query: query
    };

    for (let attempt = 0; attempt <= maxPolls; attempt++) {
      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.apiKey}`
          },
          body: JSON.stringify(payload)
        });

        if (!response.ok) {
          console.error(`HTTP error: ${response.status}`);
          return null;
        }

        const data: WeaveRecommendation = await response.json();

        if (data.status === 'completed') {
          return data;
        } else if (data.status === 'in_progress') {
          if (attempt < maxPolls) {
            // Poll again after suggested interval
            const retryAfterMs = data.retry_after_ms || pollIntervalMs;
            await new Promise(resolve => setTimeout(resolve, retryAfterMs));
            continue;
          } else {
            // Max polls reached
            return null;
          }
        } else if (data.status === 'failed') {
          console.error(`Weave auction failed: ${data.error}`);
          return null;
        }
      } catch (error) {
        console.error(`Error fetching Weave recommendation:`, error);
        return null;
      }
    }

    return null;
  }
}

