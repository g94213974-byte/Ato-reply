async def start_client(session):
    try:
        if not session:
            return None

        client = TelegramClient(
            StringSession(session),
            API_ID,
            API_HASH
        )

        await client.start()
        print("Client started")

        return client

    except Exception as e:
        print("Client error:", e)
        return None
