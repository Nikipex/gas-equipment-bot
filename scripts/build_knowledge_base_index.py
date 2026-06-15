from app.services.knowledge_base_service import knowledge_base_service

if __name__ == "__main__":
    result = knowledge_base_service.build_index()
    print(f"Knowledge chunks: {len(result.get('docs', []))}")
