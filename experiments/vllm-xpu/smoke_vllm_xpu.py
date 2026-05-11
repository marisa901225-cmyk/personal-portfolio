from vllm import LLM, SamplingParams


def main() -> None:
    model = "Qwen/Qwen2.5-0.5B-Instruct"
    llm = LLM(
        model=model,
        dtype="float16",
        max_model_len=1024,
        gpu_memory_utilization=0.75,
    )
    params = SamplingParams(temperature=0.0, max_tokens=64)
    outputs = llm.generate(
        ["Explain speculative decoding in one short sentence."],
        params,
    )
    for out in outputs:
        print(out.outputs[0].text)


if __name__ == "__main__":
    main()
