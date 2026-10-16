async def call_qwen(client, url, headers, payload):
    response = await client.post(
        url,
        headers=headers,
        json=payload
    )
    response.raise_for_status()

    result = response.json()
    return result["choices"][0]["message"]