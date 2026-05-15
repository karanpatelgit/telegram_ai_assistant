 tests = [
        "show my tasks",
        "tasks",
        "list exams",
        "exams",
        "stats",
        "remind me to study physics tomorrow at 6pm",
        "add task: gym at 7am next Monday",
        "I need to call mom tomorrow at 5pm",
        "going to finish assignment by Thursday night",
        "physics exam next Tuesday at 9am",
        "revise organic chemistry on Friday",
        "note: remember to submit fees by Monday",
        "what is the photoelectric effect",
        "should I use React or Vue",
        "study plan for 30 days covering maths physics chemistry",
        "random gibberish xyz abc 123",
    ]
 
    print("\n" + "=" * 55)
    print("  SELF TEST  (AI disabled — set use_ai=True in prod)")
    print("=" * 55)
    for msg in tests:
        result = parse_message(msg, use_ai=False)
        print(f"\n  IN  : {msg}")
        print(f"  CMD : {result['command']}")
import asyncio
async def parse_message_async(text: str, use_ai: bool = True) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, parse_message, text, use_ai)
        print(f"  ARGS: {result['args']}")
        print(f"  INFO: {describe_parsed(result)}")
    print("\n" + "=" * 55)
 
